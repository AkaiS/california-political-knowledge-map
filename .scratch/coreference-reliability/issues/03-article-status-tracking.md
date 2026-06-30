Status: ready-for-agent

## Parent

[.scratch/coreference-reliability/PRD.md](file:///Users/akaisenghor/Projects/california-political-knowledge-map/.scratch/coreference-reliability/PRD.md)

## What to build

Implement status tracking for articles processed by the ingestion pipeline in SQLite and orchestrate these status transitions in `StoryPipeline.run`.

- Define the article statuses: `UNPROCESSED`, `PROCESSING`, `COMPLETED`, `FAILED_DLQ`, `SYSTEM_ERROR`.
- Add a `status` column (defaulting to `UNPROCESSED`) to the `stories` table in SQLite schema (`sqlite_db.py`).
- Implement `update_story_status(url, status)` in the sqlite db adapter to persist status transitions in the SQLite database.
- Define a status-tracking interface/protocol (e.g. `StatusTracker`) that `StoryPipeline` can interact with, and implement a concrete SQLite version and a mock version.
- Orchestrate status transitions in `StoryPipeline.run`:
  - Set article state to `PROCESSING` at start of pipeline.
  - Set article state to `COMPLETED` on successful pipeline ingestion.
  - If coreference resolution fails to resolve after max retries, mark article state as `FAILED_DLQ` and abort processing.
  - Catch unexpected exceptions (or DLQ write failures), log them, update article state to `SYSTEM_ERROR`, and raise.
- Ensure the pipeline functions correctly in dry-run mode (do not persist status changes to the SQLite DB on dry run).

## Acceptance criteria

- [ ] Article statuses are defined (`UNPROCESSED`, `PROCESSING`, `COMPLETED`, `FAILED_DLQ`, `SYSTEM_ERROR`).
- [ ] SQLite database schema is migrated to support `status` column on `stories` table.
- [ ] `update_story_status(url, status)` is implemented in the sqlite db adapter (`sqlite_db.py`).
- [ ] A `StatusTracker` protocol or adapter interface is defined for status updates.
- [ ] `StoryPipeline` is updated to accept a status tracker dependency and `StoryPipeline.run()` updates the status to `PROCESSING` on start, `COMPLETED` on success, `FAILED_DLQ` on coreference retry exhaustion, and `SYSTEM_ERROR` on any exception or DLQ write failure.
- [ ] In dry run mode, no SQLite status changes are written.
- [ ] Integration/unit tests verify the status state machine transitions under success, retry exhaustion, filesystem failure, and random exception scenarios.

## Blocked by

- [.scratch/coreference-reliability/issues/01-structural-identity-check.md](file:///Users/akaisenghor/Projects/california-political-knowledge-map/.scratch/coreference-reliability/issues/01-structural-identity-check.md)
- [.scratch/coreference-reliability/issues/02-dead-letter-queue.md](file:///Users/akaisenghor/Projects/california-political-knowledge-map/.scratch/coreference-reliability/issues/02-dead-letter-queue.md)
