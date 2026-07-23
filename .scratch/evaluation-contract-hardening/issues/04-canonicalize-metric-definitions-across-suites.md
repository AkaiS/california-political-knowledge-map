# Canonicalize Metric Definitions across Suites

Status: completed
Labels: completed

## Parent

[Evaluation Contract and Ledger Hardening](../PRD.md)

## What to build

Make every Evaluation Metric Definition an immutable repository-wide authored definition with identity `(namespaced name, evaluator revision)` and a canonical content hash. Evaluation Suites remain self-contained by embedding their exact metric declarations, while Suite import normalizes those declarations into canonical ledger records and stores the exact Suite-to-metric relationships.

A type-agnostic evaluator may reuse one Metric Definition across different Evaluation Task Contracts when its observation value schema, semantic meaning, and comparison operation are identical. Reusing an existing identity with different semantic content must fail rather than creating apparently comparable observations with different meanings.

## Acceptance criteria

- [x] Every Evaluation Metric Definition has canonical authored content and a verified content hash covering its value type, structured schema, semantic description, and comparison operation.
- [x] Metric Definitions are imported as independently queryable immutable ledger records.
- [x] Importing identical metric content from multiple Suites is idempotent and stores one canonical definition.
- [x] Reusing `(namespaced name, evaluator revision)` with different content is rejected across Suites.
- [x] The ledger records exact Suite-to-metric relationships while authored Suites remain self-contained.
- [x] Configured Evaluator metric references resolve only to exact Metric Definitions declared by their Suite.
- [x] A semantic metric change requires a new Metric Definition revision and changes the content of every Suite revision that adopts it.
- [x] Contract and temporary-ledger tests cover reuse across task types, idempotent imports, conflict rejection, and Suite round trips.

## Blocked by

- [Persist a complete run through a decomposed Evaluation Ledger](01-persist-a-complete-run-through-a-decomposed-evaluation-ledger.md)
