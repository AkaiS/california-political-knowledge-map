Status: ready-for-agent

## Parent

[.scratch/batch-ingestion-orchestration/PRD.md](file:///Users/akaisenghor/Projects/california-political-knowledge-map/.scratch/batch-ingestion-orchestration/PRD.md)

## What to build

Establish the production CLI entry point (`ca-map`) using `pyproject.toml` pointing to a unified CLI entrypoint `src/knowledge_map/cli/main.py`. Inside the new CLI module, expose the `ingest` subcommand.

Build a new `BatchIngestionService` class that handles the sequential orchestration of unprocessed source articles:
- Load batch ingestion configuration `BatchIngestionSettings` (e.g. from environment variables via `src/knowledge_map/config.py`).
- Retrieve all articles from the SQLite database where `status` is `'UNPROCESSED'` and content is non-empty.
- Process articles sequentially by invoking `StoryPipeline.run(article)`.
- Ensure article status updates to `PROCESSING` when execution begins, and to `COMPLETED` on successful ingestion.
- Implement robust unit tests mocking the pipeline and database adapters to verify the CLI arguments, configuration parsing, the sequential execution flow, and correct database status transitions.

## Acceptance criteria

- [ ] A unified CLI entrypoint is created at `src/knowledge_map/cli/main.py` and exposed via the `ca-map` script entry point in `pyproject.toml`.
- [ ] The CLI supports the `ingest` subcommand.
- [ ] A configuration model `BatchIngestionSettings` is added to `src/knowledge_map/config.py` with settings for retries, backoff, and locking.
- [ ] `BatchIngestionService` is implemented to retrieve only stories with `status = 'UNPROCESSED'` and non-empty content.
- [ ] The ingestion loop processes stories sequentially, invoking the pipeline for each.
- [ ] Ingestion status transitions correctly from `UNPROCESSED` -> `PROCESSING` -> `COMPLETED` for successful articles.
- [ ] Comprehensive unit tests verify the sequential processing behavior, status updates, CLI argument parsing, and settings loading.

## Blocked by

None - can start immediately
