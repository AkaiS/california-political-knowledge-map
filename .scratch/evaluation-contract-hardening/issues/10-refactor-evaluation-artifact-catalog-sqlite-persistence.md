# Refactor Evaluation Artifact Catalog SQLite persistence

Status: completed
Labels: completed

## Parent

[Evaluation Contract and Ledger Hardening](../PRD.md)

## What to build

Refactor `SQLiteEvaluationArtifactCatalog` in `src/knowledge_map/evaluation/store.py` so that it directly implements and owns all SQLite query persistence logic for artifact registration, content lookup by hash, and artifact reading.

Remove reverse calls back to private methods on `SQLiteEvaluationLedger` (`_register_artifact`, `_get_artifact`, `_read_artifact`). `SQLiteEvaluationLedger` delegates artifact catalog operations down to `SQLiteEvaluationArtifactCatalog`, completing the separation required by ADR 0010.

## Acceptance criteria

- [x] `SQLiteEvaluationArtifactCatalog` executes artifact persistence, lookup, and retrieval query logic directly on its connection.
- [x] `SQLiteEvaluationLedger` delegates artifact operations to `SQLiteEvaluationArtifactCatalog`.
- [x] `SQLiteEvaluationLedger` functions strictly as a thin transaction coordinator and persistence façade without holding private SQL implementation methods.
- [x] Entire test suite remains green (`uv run pytest`).

## Blocked by

- [Refactor Evaluation Execution Store SQLite persistence](09-refactor-evaluation-execution-store-sqlite-persistence.md)
