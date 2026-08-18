# Product Requirements: Coreference Reliability Improvements

Labels: completed

> Historical record: this project improved the retired whole-article markup
> implementation. Its Structural Identity Check and tag-specific retry
> machinery were superseded by [Coreference Resolution via Mention
> Spans](../coreference-mention-spans/PRD.md); the current flow derives and
> validates Mention Spans against the original Source Article.

## Problem Statement

The former whole-article coreference output could introduce structural
modifications to the text, which made character-level alignment with the
original Source Article fragile. The current Mention Span contract avoids that
failure mode by deriving every replacement range from the original text.

The current pipeline also records per-Mention-Span outcomes and zero-survivor
failure details in the Dead Letter Queue, while retaining visibility into the
processing status of articles as they transition through ingestion.

## Solution

We will improve the coreference resolution pipeline's reliability and observability by:
1. Resolving numbered-sentence Mention Spans against the original Source Article so text outside accepted ranges remains unchanged.
2. Creating a **Dead Letter Queue (DLQ)** using the adapter pattern (`LocalFileDLQAdapter`) to write detailed Mention Span outcomes as JSON files to `.scratch/coreference_dlq/` whenever a zero-survivor failure occurs.
3. Tracking and updating the **Article Status** (`UNPROCESSED`, `PROCESSING`, `COMPLETED`, `FAILED_DLQ`, `SYSTEM_ERROR`) in the SQLite database throughout the pipeline execution. If coreference resolution fails after the retry budget, we mark the article as `FAILED_DLQ` and stop processing it.

## User Stories

1. As a system administrator, I want the coreference resolver to derive replacements from the original Source Article, so that we maintain exact content alignment.
2. As an AI engineer, I want every zero-survivor coreference failure to be written to a Dead Letter Queue (DLQ), so that I can audit and refine the LLM prompts using real failure cases.
3. As a developer, I want DLQ files to be named using the article's domain and a URL hash, so that we avoid filename length limits and file system collisions.
4. As a system operator, I want to see the status of each article in the SQLite database (e.g. `PROCESSING`, `COMPLETED`, `FAILED_DLQ`), so that I can easily track progress and identify failures.
5. As a developer, I want any DLQ file-write failure to log a warning but transition the article state to `SYSTEM_ERROR` and abort processing, so that infrastructure issues are immediately visible.

## Implementation Decisions

### Mention Span Validation and Substitution
- **Source Anchoring**: The annotator addresses references by numbered sentence label, verbatim mention text, and occurrence; Python derives the character range from the original Source Article.
- **Per-span Degradation**: A Mention Span that cannot be located or is rejected by the Coreference Critic is discarded without changing neighbouring spans.
- **Retry Integration**: Critic reasons are sent back to the annotator for rejected spans only, and a zero-survivor run is recorded as a failure rather than silently returning unresolved text.

### Dead Letter Queue (DLQ)
- **DLQ Adapter Protocol**: Define `DeadLetterQueueAdapter` protocol with `log_failure`.
- **Local File Implementation**: Build `LocalFileDLQAdapter` to write JSON documents to `.scratch/coreference_dlq/`.
- **Filename Convention**: Named as `{domain}_{url_hash}_{timestamp}_{failure_type}_retry_{retry_count}.json`.
- **Payload Schema**: Each JSON record includes the article URL, title, original text, resolution run, Mention Spans, per-span outcomes, specific validation issues, failure type, timestamp, and agent metadata (model, temperature, prompt_version, system prompt).
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
- **Coreference Adapter Seam**: Test Mention Span validation and the targeted retry loop within the coreference adapter by mocking the annotator and Critic responses and verifying the correct retry count, feedback messages, and failure behavior.
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
