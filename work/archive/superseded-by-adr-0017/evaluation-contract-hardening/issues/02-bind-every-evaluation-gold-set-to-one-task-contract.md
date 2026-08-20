# Bind every Evaluation Gold Set to one Task Contract

Labels: completed

## Parent

[Evaluation Contract and Ledger Hardening](../PRD.md)

## What to build

Make each Evaluation Gold Set version a contract-homogeneous authored population for one component operation. The Gold Set binds one exact Evaluation Task Contract, every referenced Evaluation Case revision must implement that contract, and an Evaluation Suite can pair with the Gold Set only when its Task Contract is exactly identical.

Validate membership when the Gold Set is authored and again when its references are resolved during import. Run preflight compares the Gold Set and Suite contracts once before selection; selected-manifest validation remains defense in depth. Subset selection may vary splits, tags, and Evaluation Requirement coverage, but cannot conceal a task-schema incompatibility.

## Acceptance criteria

- [x] An Evaluation Gold Set version records one exact input, expected-output, and metadata schema contract as semantic authored content.
- [x] Gold Set construction rejects any member whose exact schema identity, revision, or fingerprint differs from the bound Task Contract.
- [x] Import rejects membership references that resolve to incompatible Evaluation Case revisions or to content different from the referenced immutable revision.
- [x] Suite-to-Gold-Set preflight rejects a Task Contract mismatch before selection or run creation.
- [x] A selected Evaluation Case Manifest is revalidated against the already-matched Task Contract without permitting selection to hide an incompatible Gold Set member.
- [x] Legitimate heterogeneous case shapes remain supported only as explicit variants inside the shared Pydantic schemas.
- [x] Contract, import, full-run, and subset-run tests cover compatible populations and every mismatch dimension.

## Blocked by

- [Persist a complete run through a decomposed Evaluation Ledger](01-persist-a-complete-run-through-a-decomposed-evaluation-ledger.md)
