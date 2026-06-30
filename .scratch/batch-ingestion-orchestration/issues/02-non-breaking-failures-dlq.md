Status: ready-for-agent

## Parent

[.scratch/batch-ingestion-orchestration/PRD.md](file:///Users/akaisenghor/Projects/california-political-knowledge-map/.scratch/batch-ingestion-orchestration/PRD.md)

## What to build

Implement exception classification for non-breaking ingestion errors (e.g. `CoreferenceResolutionError`, `ExtractionError`, or metadata validation/schema failures) and integrate them into the `BatchIngestionService` execution flow. 

When a non-breaking failure occurs on an article:
- Catch the exception inside the batch processing loop.
- Log a warning with the error details.
- Write the failure payload to the Dead Letter Queue using the `DeadLetterQueueAdapter`.
- Update the article's status in the SQLite database to `FAILED_DLQ`.
- Safely log and proceed to the next article in the queue, ensuring one bad document does not abort the entire batch run.

## Acceptance criteria

- [ ] Exception classification helper `classify_exception` identifies non-breaking errors such as `CoreferenceResolutionError` and `ExtractionError`.
- [ ] Ingestion service handles non-breaking exceptions inside the sequential loop.
- [ ] Non-breaking exceptions trigger logging to the DLQ via `DeadLetterQueueAdapter`.
- [ ] Failed articles have their database status updated to `FAILED_DLQ`.
- [ ] The batch ingestion loop continues processing subsequent articles after encountering a non-breaking error.
- [ ] Mock-driven unit tests verify that simulated non-breaking errors log to the DLQ, update database status, and allow the loop to continue.

## Blocked by

- [.scratch/batch-ingestion-orchestration/issues/01-batch-ingestion-cli-and-loop.md](file:///Users/akaisenghor/Projects/california-political-knowledge-map/.scratch/batch-ingestion-orchestration/issues/01-batch-ingestion-cli-and-loop.md)
