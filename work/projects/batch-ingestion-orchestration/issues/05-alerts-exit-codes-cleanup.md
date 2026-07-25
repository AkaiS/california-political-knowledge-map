Labels: completed

## Parent

[.scratch/batch-ingestion-orchestration/PRD.md](file:///Users/akaisenghor/Projects/california-political-knowledge-map/work/projects/batch-ingestion-orchestration/PRD.md)

## What to build

Integrate high-visibility operator alerts, map robust exit status codes across the CLI, and complete the deprecation and transition from `playground.py` to the unified `ca-map` CLI.

- Implement a `ConsoleNotifier` utility to print distinct, high-visibility warning blocks/banners to `sys.stderr` when critical failures occur (such as consecutive rate limit lock triggers or unrecoverable database connectivity failure).
- Ensure all commands and subcommands explicitly bubble up appropriate exit codes:
  - `0` on successful runs (such as a fully completed batch or successful janitor recovery).
  - Non-zero codes (like `1` or custom error codes) on system crashes, active lock file detection, or unrecoverable adapter errors.
- Migrate the remaining administrative tools from `src/knowledge_map/cli/playground.py` (specifically `clear` and `analyze` subcommands) into `src/knowledge_map/cli/main.py`.
- Delete `src/knowledge_map/cli/playground.py` and its corresponding tests once they are fully transitioned to the unified CLI.
- Run final end-to-end sanity tests on all subcommands.

## Acceptance criteria

- [x] `ConsoleNotifier` prints eye-catching console banners for critical failures and locks.
- [x] The CLI returns non-zero exit codes for halts, rate-limit locks, and unrecoverable exceptions.
- [x] Administrative subcommands (`clear`, `analyze`) are fully migrated from `playground.py` to `src/knowledge_map/cli/main.py`.
- [x] The deprecated file `src/knowledge_map/cli/playground.py` is deleted.
- [x] CLI test suite is updated to cover the new subcommands in `src/knowledge_map/cli/main.py` and verify appropriate exit codes.

## Blocked by

- [.scratch/batch-ingestion-orchestration/issues/04-health-checks-and-janitor.md](file:///Users/akaisenghor/Projects/california-political-knowledge-map/work/projects/batch-ingestion-orchestration/issues/04-health-checks-and-janitor.md)
