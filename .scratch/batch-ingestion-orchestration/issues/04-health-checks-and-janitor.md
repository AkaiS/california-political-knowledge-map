Status: ready-for-agent

## Parent

[.scratch/batch-ingestion-orchestration/PRD.md](file:///Users/akaisenghor/Projects/california-political-knowledge-map/.scratch/batch-ingestion-orchestration/PRD.md)

## What to build

Implement individual adapter health checks and the janitor healing CLI command to automate service recovery.

- Add a standard `health_check(self) -> bool` method/protocol to all adapters:
  - `EmbeddingAdapter` validates connectivity via a minimal embedding API call.
  - `CoreferenceAdapter` and `EntityExtractionAdapter` validate via a minimal, single-token completion API call.
  - `DatabaseAdapter` checks database connectivity with a simple test query (e.g., `RETURN 1` or equivalent).
- Implement the `ca-map janitor` CLI command.
- The janitor command reads `.scratch/pipeline.lock` (if present), determines the locked component, triggers that component's `health_check()` method, and deletes the lock file if the check passes.

## Acceptance criteria

- [ ] `health_check(self) -> bool` is added to all adapter protocols and concrete implementations.
- [ ] Subcommand `janitor` is added to the unified CLI in `src/knowledge_map/cli/main.py`.
- [ ] Janitor parses the locked component from `.scratch/pipeline.lock`.
- [ ] Janitor runs the corresponding adapter's health check probe.
- [ ] Lock file `.scratch/pipeline.lock` is deleted if and only if the health check probe returns `True`.
- [ ] Unit tests verify adapter health check probes, lock parsing, and file deletion on success.

## Blocked by

- [.scratch/batch-ingestion-orchestration/issues/03-rate-limit-retry-backoff-and-pipeline-locking.md](file:///Users/akaisenghor/Projects/california-political-knowledge-map/.scratch/batch-ingestion-orchestration/issues/03-rate-limit-retry-backoff-and-pipeline-locking.md)
