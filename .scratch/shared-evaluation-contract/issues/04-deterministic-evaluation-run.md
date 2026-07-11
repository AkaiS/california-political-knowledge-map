# 04. Execute and Record a Complete Deterministic Evaluation Run

Status: completed

## Parent

[Shared Evaluation Contract and Record Model](../PRD.md)

## What to build

An evaluation runner can execute a typed Evaluation Suite through the provider-neutral task protocol using deterministic task and evaluator doubles. Before work begins, it creates an immutable Evaluation Run with a secret-free Evaluation Run Configuration, linked suite and Gold Set revisions, and an authoritative frozen Evaluation Case Manifest.

For a successful run, the coordinator persists exactly one Evaluation Case Result for every manifested case, every case and report evaluator invocation, and their case- and run-level Evaluation Metric Observations. It runs report evaluators after case evaluation against the complete manifest and all corresponding results.

## Acceptance criteria

- [x] A full or subset execution resolves selection once, freezes exact case revisions in an Evaluation Case Manifest, and records selection provenance without treating the selection expression as authoritative.
- [x] Run creation, its manifest, and pending Case Result envelopes are committed atomically before tasks start.
- [x] A deterministic typed task executes through `pydantic-evals` and yields exactly one Case Result per manifested case.
- [x] Every actual case evaluator and report evaluator application has its own execution record, including invocations that emit no observations.
- [x] Report evaluators receive the complete manifest and matching Case Results, emit run observations, and make denominator/exclusion treatment explicit.
- [x] Scalar observations persist in typed columns and structured observations as validated JSON, with an exactly-one-value invariant and subject-specific case/run foreign keys.

## Blocked by

- [Define Executable Evaluation Suites and Metric Semantics](02-executable-suites-and-metrics.md)
- [Persist Imported Definitions and the Evaluation Artifact Catalog](03-evaluation-ledger-and-artifact-catalog.md)
