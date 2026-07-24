# Refactor Evaluation Artifact Catalog SQLite persistence

Status: ready-for-agent
Labels: ready-for-agent

## Parent

[Evaluation Contract and Ledger Hardening](../PRD.md)

## What to build

Refactor `SQLiteEvaluationArtifactCatalog` in `src/knowledge_map/evaluation/store.py` so that it directly implements and owns all SQLite query persistence logic for artifact registration, content lookup by hash, and artifact reading.

Remove reverse calls back to private methods on `SQLiteEvaluationLedger` (`_register_artifact`, `_get_artifact`, `_read_artifact`). `SQLiteEvaluationLedger` delegates artifact catalog operations down to `SQLiteEvaluationArtifactCatalog`, completing the separation required by ADR 0010.

## Acceptance criteria

- [ ] `SQLiteEvaluationArtifactCatalog` executes artifact persistence, lookup, and retrieval query logic directly on its connection.
- [ ] `SQLiteEvaluationLedger` delegates artifact operations to `SQLiteEvaluationArtifactCatalog`.
- [ ] `SQLiteEvaluationLedger` functions strictly as a thin transaction coordinator and persistence façade without holding private SQL implementation methods.
- [ ] Entire test suite remains green (`uv run pytest`).

## Blocked by

- [Refactor Evaluation Execution Store SQLite persistence](09-refactor-evaluation-execution-store-sqlite-persistence.md)
