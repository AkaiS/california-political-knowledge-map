# Preflight selected cases into a Resolved Evaluation Plan

Status: ready-for-agent
Labels: ready-for-agent

## Parent

[Case Evaluation Requirements and Resumable Evaluation Execution](../PRD.md)

## What to build

Resolve the exact Evaluation Case revisions selected from an Evaluation Gold Set against an Evaluation Suite before any run is created. A successful preflight produces the immutable Resolved Evaluation Plan that explains exactly which Configured Evaluators will run for each case and why.

## Acceptance criteria

- [ ] Preflight retains exact Evaluation Task Contract compatibility checks and validates requirements only for the cases selected for the proposed run.
- [ ] Unknown catalog keys and requirements without Suite bindings reject the pairing before run creation.
- [ ] Full-run preflight reports every incompatible selected case and requirement in one result rather than stopping at the first gap.
- [ ] Unsupported unselected cases do not prevent a compatible subset from resolving.
- [ ] The plan captures the exact Suite revision, manifested Evaluation Case revisions, each case's declared requirements, and every effective Configured Evaluator reference.
- [ ] Effective case evaluators are the additive union of Suite-wide Case Evaluators and every relevant binding.
- [ ] A Configured Evaluator selected through overlapping scopes or requirements appears once per case while retaining Suite-wide and all requirement provenance.
- [ ] Canonical compact JSON serialization is deterministic, and any readable JSON or YAML projection is explicitly derived rather than authoritative.
- [ ] Behavioral tests cover Suite-wide application, multiple requirements, deduplication, provenance, subset compatibility, and complete coverage-gap reporting.

## Blocked by

- [Author Evaluation Requirements and Suite bindings](01-author-evaluation-requirements-and-suite-bindings.md)
- [Bind every Evaluation Gold Set to one Task Contract](../../evaluation-contract-hardening/issues/02-bind-every-evaluation-gold-set-to-one-task-contract.md)
