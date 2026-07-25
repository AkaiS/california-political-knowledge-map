# Product Requirements: Coreference Reliability Improvements

Labels: completed

## Problem Statement

During coreference resolution, the LLM-based annotator agent can introduce structural modifications to the text (such as deleting words, adding punctuation, or changing sentence structures). When this happens, we lose character-level alignment with the original Source Article, causing downstream ingestion problems. 

Additionally, if the coreference resolution fails (either due to structural mismatch or the Critic agent repeatedly rejecting the annotations), the pipeline falls back silently to the original text without logging the failure details for offline auditing or prompt debugging. There is also no visibility into the processing status of articles as they transition through the ingestion pipeline.

## Solution

We will improve the coreference resolution pipeline's reliability and observability by:
1. Implementing a programmatic **Structural Identity Check** that runs immediately after annotation to ensure the text structure is unchanged.
2. Creating a **Dead Letter Queue (DLQ)** using the adapter pattern (`LocalFileDLQAdapter`) to write detailed failure records as JSON files to `.scratch/coreference_dlq/` whenever a check fails.
3. Tracking and updating the **Article Status** (`UNPROCESSED`, `PROCESSING`, `COMPLETED`, `FAILED_DLQ`, `SYSTEM_ERROR`) in the SQLite database throughout the pipeline execution. If coreference resolution fails to resolve after max retries, we mark the article as `FAILED_DLQ` and stop processing it.

## User Stories

1. As a system administrator, I want the coreference resolver to reject any annotations that modify the original text structure, so that we maintain exact content alignment.
2. As an AI engineer, I want every coreference annotation check failure (structural or critic-based) to be written to a Dead Letter Queue (DLQ), so that I can audit and refine the LLM prompts using real failure cases.
3. As a developer, I want DLQ files to be named using the article's domain and a URL hash, so that we avoid filename length limits and file system collisions.
4. As a system operator, I want to see the status of each article in the SQLite database (e.g. `PROCESSING`, `COMPLETED`, `FAILED_DLQ`), so that I can easily track progress and identify failures.
5. As a developer, I want any DLQ file-write failure to log a warning but transition the article state to `SYSTEM_ERROR` and abort processing, so that infrastructure issues are immediately visible.

## Implementation Decisions

### Structural Identity Check
- **Tag Stripping Logic**: A helper function replaces `<ref entity="Canonical Name">pronoun</ref>` tags with their inner text (the pronoun).
- **Whitespace Normalization**: Prior to comparison, both the stripped text and the original text are normalized by trimming outer whitespace and collapsing multiple spaces/newlines to single ones.
- **Retry Integration**: The check runs programmatically on every annotator output. If it fails, the retry loop decrements the budget, bypasses the LLM Critic agent to save tokens, and feeds the mismatch error back to the annotator.

### Dead Letter Queue (DLQ)
- **DLQ Adapter Protocol**: Define `DeadLetterQueueAdapter` protocol with `log_failure`.
- **Local File Implementation**: Build `LocalFileDLQAdapter` to write JSON documents to `.scratch/coreference_dlq/`.
- **Filename Convention**: Named as `{domain}_{url_hash}_{timestamp}_{failure_type}_retry_{retry_count}.json`.
- **Payload Schema**: Each JSON record includes the article URL, title, original text, failed annotated text, specific validation issues, failure type, timestamp, and agent metadata (model, temperature, prompt_version, system prompt).
- **Failure Recovery**: File system write errors are caught, logged, and trigger a pipeline crash with status set to `SYSTEM_ERROR`.

### Pipeline & Database Status Tracking
- **State Machine**: Define article statuses: `UNPROCESSED`, `PROCESSING`, `COMPLETED`, `FAILED_DLQ`, `SYSTEM_ERROR`.
- **SQLite Status Tracking**:
  - Add a `status` column (defaulting to `UNPROCESSED`) to the `stories` table in SQLite schema (`sqlite_db.py`).
  - Implement `update_story_status(url, status)` in the sqlite db adapter to persist status transitions in the SQLite database.
  - Define a protocol/adapter interface for status tracking (e.g., `StatusTracker`) that `StoryPipeline` interacts with.
- **Pipeline Orchestration**:
  - Sets state to `PROCESSING` at start in SQLite.
  - Halts article processing if coreferences fail after max retries, updating state to `FAILED_DLQ` in SQLite.
  - Catches unexpected exceptions, marks state as `SYSTEM_ERROR` in SQLite, and halts.
  - Updates state to `COMPLETED` in SQLite on successful ingestion.

## Testing Decisions

### Seams for Testing
- **Coreference Adapter Seam**: Test the validation/retry loop within the coreference adapter by mocking the annotator to return structurally modified text and verifying the correct retry count, feedback messages, and fallback behavior.
- **Dead Letter Queue (DLQ) Seam**: Test `LocalFileDLQAdapter` using a temporary directory to verify that files are successfully written with correct structure and naming.
- **Pipeline Status Seam**: Test `StoryPipeline.run` using mock adapters to assert that status transitions (`PROCESSING` -> `COMPLETED` / `FAILED_DLQ` / `SYSTEM_ERROR`) are executed in the status tracker/SQLite adapter under all scenarios.

### Prior Art
- `tests/test_coreference.py` contains tests that mock `pydantic_ai.Agent` runs using `FunctionModel` and verify retries.
- `tests/test_pipeline.py` contains mock adapter tests (`MockDatabaseAdapter`, etc.) verifying `StoryPipeline` state.

## Out of Scope
- Re-processing files from the Dead Letter Queue automatically.
- Tracking status for individual article chunks (tracking is kept at the article level).
- Storing DLQ failures in Neo4j (local file system is used to prevent DB overhead).

## Further Notes

None.
