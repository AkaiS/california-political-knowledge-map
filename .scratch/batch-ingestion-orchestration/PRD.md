Status: ready-for-agent

# Product Requirements Document: Batch Ingestion Orchestration and Resiliency

## Problem Statement

Currently, the ingestion pipeline runs on articles either one-by-one or procedurally through the playground script (`playground.py`). However, any failure in the pipeline—whether it is a non-breaking error (like coreference resolution structural mismatch or entity extraction validation failure) or a system-level error (like database connection issues, network timeouts, or API rate limits)—causes the entire execution to abort immediately. 

There is no mechanism to skip bad articles and continue ingesting the rest of the queue, nor is there a structured way to handle transient infrastructure or API rate limit errors (HTTP 429) using exponential backoff. Additionally, if the pipeline halts due to persistent rate limiting, it continues to run and fail on subsequent cron schedules, wasting computational resources and API tokens. There is also no way to notify the operator when a batch run has crashed or to automatically check when rate-limited APIs have recovered.

## Solution

We will build a robust `BatchIngestionService` and a unified production CLI entry point (`src/knowledge_map/cli/main.py`) to orchestrate batch ingestion of unprocessed documents.

1. **Batch Ingestion Service:** Process articles sequentially. Non-breaking failures (such as `CoreferenceResolutionError` or `ExtractionError`) are caught, logged to the DLQ, and updated to `FAILED_DLQ` in the database, allowing the runner to proceed to the next article.
2. **Exponential Backoff & Differentiated Retries:** 
   * **Network/Timeout Errors:** Retry the failed adapter operation up to 3 times with progressive backoff.
   * **Rate Limits (HTTP 429):** Parse the `Retry-After` header if present. If the header specifies a delay under our configured cap (e.g., 2 minutes), sleep for that duration. If it exceeds the cap, skip the current article, increment the consecutive rate limit failure count, and move to the next document. If the header is missing, fall back to a longer exponential backoff time horizon (ensuring the final retry waits at least 1 minute). 
3. **Pipeline Locking & Consecutive Failure Limit:** If we encounter 3 consecutive rate limit failures on any adapter across different articles, write a lock file (`.scratch/pipeline.lock`) identifying the failed component (e.g., `embedding`, `coreference`, `extraction`) and halt the batch process.
4. **Janitor Process:** A lightweight command/process (`ca-map janitor`) that reads the lock file, triggers a component-specific `health_check()` probe on the rate-limited adapter, and deletes the lock file on success to allow ingestion to resume.
5. **Operator Alerts & Exit Codes:** Integrate a `ConsoleNotifier` to print high-visibility alerts on critical failure, and terminate with a non-zero exit code so cron/monitoring tools detect the crash.
6. **Unified Production CLI:** Transition away from `playground.py` and register `ca-map` in `pyproject.toml` with subcommands `ingest` and `janitor`.

## User Stories

1. As a system operator, I want to execute batch ingestion of all unprocessed articles with a single command, so that I don't have to trigger ingestion manually for each story.
2. As a system operator, I want the ingestion service to filter out already completed or failed articles, so that we do not duplicate processing or waste tokens.
3. As a developer, I want the status of each article to transition to `PROCESSING` at start and `COMPLETED` on successful ingestion, so that we have live database visibility.
4. As a system operator, I want non-breaking errors on a single article (like coreference mismatches) to log a warning, mark the article status as `FAILED_DLQ`, and continue to the next article, so that one bad document doesn't block the entire queue.
5. As an AI engineer, I want the details of any coreference resolution failure during a batch run to be captured in the Dead Letter Queue (DLQ), so that I can debug and refine the LLM prompts.
6. As a system administrator, I want HTTP 429 rate limit errors to check for a `Retry-After` header, so that we sleep for the exact duration requested by the provider when it is within our wait cap (e.g., 2 minutes).
7. As a system administrator, I want the ingestion service to skip an article and move to the next one if the `Retry-After` duration exceeds our wait cap, so that a single long rate limit doesn't hang the entire batch run.
8. As a system administrator, I want rate limit errors without a `Retry-After` header to back off on a longer time horizon (reaching at least 1 minute on the final retry), so that the API has time to recover.
9. As a developer, I want transient network timeouts or connection failures to be retried up to 3 times, so that brief network blips do not cause the batch ingestion to crash.
10. As a system administrator, I want the batch ingestion to halt and write a `.scratch/pipeline.lock` file if it hits 3 consecutive rate limit errors across different articles, so that we avoid hammering a blocked API.
11. As a system administrator, I want the lock file to store JSON data specifying which component (e.g., `embedding`, `coreference`) was rate limited, so that the janitor knows what to probe.
12. As a system administrator, I want the batch ingestion process to fail fast and exit immediately if a lock file is present, so that overlapping cron jobs do not run while the API is rate-limited.
13. As a developer, I want all adapters to implement a standard `health_check()` method, so that probe logic is encapsulated inside the adapter responsible for that resource.
14. As a system operator, I want a janitor command to run target-specific probes against the rate-limited adapter identified in the lock file, so that we can check if the API is healthy again.
15. As a system operator, I want the janitor command to delete the lock file once the probe passes, so that the next scheduled batch ingestion can run.
16. As a developer, I want mock-driven unit tests, so that I can verify the backoff calculations, consecutive failure counts, lock creation, and janitor healing without hitting real APIs.
17. As a system administrator, I want critical batch failures to write to the standard error logs and terminate with a non-zero exit code, so that my cron manager detects the failure and alerts me.

## Implementation Decisions

### Batch Ingestion Service
- **Sequential Ingestion Loop:** A class `BatchIngestionService` iterates over the unprocessed queue. It processes one article at a time by invoking a helper method `process_article(self, article: SourceArticle)`.
- **Exception Classification:** We define a helper function `classify_exception(exc: Exception) -> ErrorType` to map exceptions to either `NON_BREAKING` (e.g., `CoreferenceResolutionError`, `ExtractionError`), `RATE_LIMIT` (e.g., `openai.RateLimitError` or HTTP 429 status codes), or `CONNECTIVITY` (e.g., timeout or socket errors).
- **Centralized Configuration:** Define a `BatchIngestionSettings` model in `config.py` loaded from environment variables containing retry counts, backoff parameters, and `rate_limit_wait_cap_seconds` (default 120 seconds).
- **Retry-After Enforcement:**
  - If a 429 error occurs and contains a `Retry-After` header, parse the delay (seconds).
  - If `delay <= rate_limit_wait_cap_seconds`, pause execution for `delay` and retry processing the current article.
  - If `delay > rate_limit_wait_cap_seconds`, skip the current article (leaving it marked as unprocessed), increment `consecutive_api_rate_limit_failures`, and proceed to the next article in the queue.

### Locking & Pipeline Janitor
- **Consecutive Error Tracking:** Keep a counter in memory during the batch run. A successful article resets this counter. 3 consecutive rate limit failures trigger pipeline locking.
- **Lock File Payload:** Written to `.scratch/pipeline.lock` containing the locked timestamp, component name, and last exception message.
- **Adapter Health Check Protocol:** Add `health_check(self) -> bool` to the adapter protocols.
  - `EmbeddingAdapter` checks by doing a dummy embedding call.
  - `CoreferenceAdapter` and `EntityExtractionAdapter` check by executing a single-token completion call.
  - `DatabaseAdapter` checks by running a simple query (e.g., `RETURN 1`).

### Production CLI Entry Point
- **Unified CLI:** Expose a new entry point `src/knowledge_map/cli/main.py`.
- **Subcommands:** Expose `ingest` and `janitor` subcommands, migrating database clean/analyze utilities away from `playground.py`.
- **Packaging:** Register `ca-map` script entry point in `pyproject.toml` pointing to `knowledge_map.cli.main:main`.

## Testing Decisions

- **Test Seam:** We will test the `BatchIngestionService` using unit tests that mock the adapter protocols (`DatabaseAdapter`, `EmbeddingAdapter`, etc.). This isolates the retry logic, lock creation, and consecutive error counting from network/database status.
- **Scope of Tests:**
  - Verify that a network connectivity error retries 3 times and halts.
  - Verify that a rate limit error retries according to the backoff schedule (hitting $\ge$ 1 minute sleep on the last try).
  - Verify that 3 consecutive rate limit errors write a lock file and stop ingestion.
  - Verify that the janitor deletes the lock file when the adapter's `health_check()` returns `True`.
- **Prior Art:** Existing tests in `tests/test_coreference.py` and `tests/test_pipeline.py` which mock agents using `FunctionModel` and verify retry counts.

## Out of Scope

- Reprocessing locked/failed articles automatically within the same run once a lock is written.
- Retrying non-breaking errors (they are sent directly to DLQ and the database status is marked `FAILED_DLQ`; they must be retried manually or via a separate script).
- Concurrent thread orchestration inside `BatchIngestionService` (kept sequential for safety and simplicity).

## Further Notes

None.

