# Refactor Authored Definition Catalog SQLite persistence

Status: completed
Labels: completed

## Parent

[Evaluation Contract and Ledger Hardening](../PRD.md)

## What to build

Refactor `SQLiteAuthoredDefinitionCatalog` in `src/knowledge_map/evaluation/store.py` so that it directly implements and owns all SQLite query persistence logic for authored evaluation definitions and metric definitions. 

Remove reverse calls back to private methods on `SQLiteEvaluationLedger` (`_import_definition`, `_import_metric_definition`, `_get_definition`, `_get_metric_definition`, `_list_definitions`, `_list_metric_definitions`, `_list_suite_metric_definitions`, `_list_gold_set_memberships`). The `SQLiteEvaluationLedger` façade should delegate definition catalog queries down to `SQLiteAuthoredDefinitionCatalog` while remaining the transaction boundary owner.

## Acceptance criteria

- [x] `SQLiteAuthoredDefinitionCatalog` executes SQLite query logic directly on its database connection rather than calling private methods on `SQLiteEvaluationLedger`.
- [x] `SQLiteEvaluationLedger` delegates definition catalog operations to `SQLiteAuthoredDefinitionCatalog`.
- [x] All authored definition and metric unit tests pass (`uv run pytest tests/test_evaluation_definitions.py`).
- [x] Entire test suite remains green (`uv run pytest`).

## Blocked by

- None — can start immediately.
