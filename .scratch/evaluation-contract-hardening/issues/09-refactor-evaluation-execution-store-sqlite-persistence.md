# Refactor Evaluation Execution Store SQLite persistence

Status: completed
Labels: completed

## Parent

[Evaluation Contract and Ledger Hardening](../PRD.md)

## What to build

Refactor `SQLiteEvaluationExecutionStore` in `src/knowledge_map/evaluation/store.py` so that it directly implements and owns all SQLite query persistence and checkpoint logic for evaluation runs, case evaluations, report evaluations, and guarded run completions.

Remove reverse calls back to private methods on `SQLiteEvaluationLedger` (`_create_evaluation_run`, `_record_case_evaluation`, `_record_report_evaluation`, `_complete_evaluation_run`). `SQLiteEvaluationLedger` delegates run execution and checkpoint operations down to `SQLiteEvaluationExecutionStore`.

## Acceptance criteria

- [x] `SQLiteEvaluationExecutionStore` executes run creation, case recording, report recording, and run completion query logic directly.
- [x] `SQLiteEvaluationLedger` delegates execution lifecycle operations to `SQLiteEvaluationExecutionStore`.
- [x] All run lifecycle unit tests pass (`uv run pytest tests/test_evaluation_runs.py`).
- [x] Entire test suite remains green (`uv run pytest`).

## Blocked by

- [Refactor Authored Definition Catalog SQLite persistence](08-refactor-authored-definition-catalog-sqlite-persistence.md)
