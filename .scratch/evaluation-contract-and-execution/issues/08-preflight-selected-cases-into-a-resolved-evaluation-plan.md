# Preflight selected cases into a Resolved Evaluation Plan

Labels: ready-for-agent

## Parent

[Evaluation Contract and Resumable Execution](../PRD.md)

## What to build

Resolve the exact Evaluation Case revisions selected from an Evaluation Gold Set against an exact imported Evaluation Suite before any run is created. A successful preflight produces the immutable Resolved Evaluation Plan that identifies the authoritative Suite revision and explains exactly which Configured Evaluators will run for each case and why.

## Acceptance criteria

- [ ] Preflight retains exact Evaluation Task Contract compatibility checks and validates requirements only for the cases selected for the proposed run.
- [ ] Unknown catalog keys and requirements without Suite bindings reject the pairing before run creation.
- [ ] Full-run preflight reports every incompatible selected case and requirement in one result rather than stopping at the first gap.
- [ ] Unsupported unselected cases do not prevent a compatible subset from resolving.
- [ ] The plan captures the exact imported Suite identity, revision, and content hash; manifested Evaluation Case revisions; each case's declared requirements; and every effective case Configured Evaluator reference.
- [ ] The plan contains enough Suite identity to let later execution and finalization retrieve and hash-verify that exact imported Suite from the Evaluation Ledger without a caller-provided Suite object.
- [ ] Effective case evaluators are the additive union of Suite-wide Case Evaluators and every relevant binding.
- [ ] A Configured Evaluator selected through overlapping scopes or requirements appears once per case while retaining Suite-wide and all requirement provenance.
- [ ] Canonical compact JSON serialization is deterministic, and any readable JSON or YAML projection is explicitly derived rather than authoritative.
- [ ] Behavioral tests cover Suite-wide application, multiple requirements, deduplication, provenance, subset compatibility, and complete coverage-gap reporting.

## Blocked by

- [Author Evaluation Requirements and Suite bindings](07-author-evaluation-requirements-and-suite-bindings.md)
- [Bind every Evaluation Gold Set to one Task Contract](02-bind-every-evaluation-gold-set-to-one-task-contract.md)
