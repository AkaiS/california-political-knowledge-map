# 05. Preserve Incomplete, Failed, and Retried Evaluation Run Evidence

Status: completed

## Parent

[Shared Evaluation Contract and Record Model](../PRD.md)

## What to build

Evaluation operators retain trustworthy evidence when execution is not wholly successful. A Case Result independently records its execution disposition, typed task outcome, and evaluator outcomes, so provider-neutral task failures never become evaluator failures and failed evaluations never erase prior completed evidence.

The Evaluation Run lifecycle distinguishes `COMPLETED`, `FAILED`, and `CANCELLED` by workflow completion, preserves partial report evaluation, links retries as distinct immutable runs, and keeps task quality, evaluator success, missing metrics, and release-gate outcomes separately diagnosable.

## Acceptance criteria

- [x] Task outcomes use a typed success-or-failure union; failures retain a normalized category, exception type, safe message, retryability, and failure evidence without provider SDK objects.
- [x] Task failure, case evaluator failure, report evaluator failure, missing required metrics, and gate failure remain separately visible in the resulting evidence.
- [x] Completed case and report-evaluator producer records commit atomically and incrementally; an interruption after selected commits retains completed evidence and leaves the run incomplete.
- [x] `COMPLETED` means all expected workflow records reached terminal outcomes, while run-level infrastructure/orchestration failure is `FAILED` and deliberate stopping is `CANCELLED`.
- [x] Cancelled and partially reported runs retain their evidence, and a retry creates a new linked Evaluation Run rather than overwriting its predecessor.
- [x] Deterministic lifecycle tests cover successful, task-failed, evaluator-failed, cancelled, orchestration-failed, partial, and retried runs without a live provider.

## Blocked by

- [Execute and Record a Complete Deterministic Evaluation Run](04-deterministic-evaluation-run.md)
