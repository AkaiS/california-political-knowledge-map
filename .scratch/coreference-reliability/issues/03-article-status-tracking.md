Status: ready-for-agent

## Parent

[.scratch/coreference-reliability/PRD.md](file:///Users/akaisenghor/Projects/california-political-knowledge-map/.scratch/coreference-reliability/PRD.md)

## What to build

Implement status tracking for articles processed by the ingestion pipeline and orchestrate these status transitions in `StoryPipeline.run`.

- Define the article statuses: `UNPROCESSED`, `PROCESSING`, `COMPLETED`, `FAILED_DLQ`, `SYSTEM_ERROR`.
- Add `update_article_status(url, status)` to the `DatabaseAdapter` interface.
- Implement `update_article_status` in `Neo4jAdapter` using a Cypher `MERGE`/`SET` query, and update `MockDatabaseAdapter` to support the interface.
- Orchestrate status transitions in `StoryPipeline.run`:
  - Set article state to `PROCESSING` at start of pipeline.
  - Set article state to `COMPLETED` on successful pipeline ingestion.
  - If coreference resolution fails to resolve after max retries, mark article state as `FAILED_DLQ` and abort processing.
  - Catch unexpected exceptions (or DLQ write failures), log them, update article state to `SYSTEM_ERROR`, and raise.
- Ensure the pipeline functions correctly in dry-run mode (do not persist status changes to the DB on dry run).

## Acceptance criteria

- [ ] Article statuses are defined (`UNPROCESSED`, `PROCESSING`, `COMPLETED`, `FAILED_DLQ`, `SYSTEM_ERROR`).
- [ ] `DatabaseAdapter` interface is updated with `update_article_status(url, status)`.
- [ ] `Neo4jAdapter.update_article_status()` is implemented with a Cypher query.
- [ ] `MockDatabaseAdapter` implements `update_article_status()` for unit testing.
- [ ] `StoryPipeline.run()` updates database status to `PROCESSING` on start, `COMPLETED` on success, `FAILED_DLQ` on coreference retry exhaustion, and `SYSTEM_ERROR` on any exception or DLQ write failure.
- [ ] In dry run mode, no database status changes are written.
- [ ] Integration tests verify the status state machine transitions under success, retry exhaustion, filesystem failure, and random exception scenarios.

## Blocked by

- [.scratch/coreference-reliability/issues/01-structural-identity-check.md](file:///Users/akaisenghor/Projects/california-political-knowledge-map/.scratch/coreference-reliability/issues/01-structural-identity-check.md)
- [.scratch/coreference-reliability/issues/02-dead-letter-queue.md](file:///Users/akaisenghor/Projects/california-political-knowledge-map/.scratch/coreference-reliability/issues/02-dead-letter-queue.md)
