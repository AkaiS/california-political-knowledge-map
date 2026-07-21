# Resume Evaluation Finalization from a materialized aggregate manifest

Labels: ready-for-agent

## Parent

[Case Evaluation Requirements and Resumable Evaluation Execution](../PRD.md)

## What to build

Make explicit Evaluation Finalization load the Frozen Aggregate Manifest, verify its immutable checkpoint graph, and materialize a typed, ephemeral Pydantic Evaluation Report from the frozen definitions and terminal checkpoint evidence. The materialized report is the input to report evaluators but is not an additional persisted authority. A fully rendered or serialized report may be emitted as a derived export, but finalization correctness depends only on the manifest and its referenced authoritative evidence.

Dispatch materialization by evidence-contract version and reject unsupported contracts, unresolved schemas, fingerprint mismatches, missing checkpoints, and content-hash mismatches. Preserve the existing same-run finalization behavior: completed and failed Report Evaluator Executions are terminal, only missing work runs, and the finalization claim prevents competing workers from producing duplicate evidence.

## Acceptance criteria

- [ ] Evaluation Finalization loads the exact frozen Suite, Resolved Evaluation Plan, Frozen Aggregate Manifest, immutable Evaluation Case revisions, and referenced terminal checkpoints without consulting mutable authored state.
- [ ] Every manifest reference and checkpoint content hash is verified before any report evaluator executes.
- [ ] The materializer reconstructs concrete task input, expected-output, actual-output, metadata, and extensible payload types through their governing schema references and builds a semantically equivalent typed Evaluation Report in manifest order.
- [ ] Materialization preserves evaluator result categories, values, reasons, authoritative evaluator-version tags, failures, durations, attributes, artifacts, trace provenance, task failures, and report-level metadata required by report evaluators.
- [ ] Materialization dispatches by evidence-contract version; unsupported versions and schema or fingerprint mismatches fail explicitly rather than degrading to untyped values or altered semantics.
- [ ] A materializer refactor that preserves the evidence contract does not require a new persisted version, while an evaluator-visible semantic change requires a new evidence-contract version and reader path.
- [ ] Finalization executes only report evaluators without terminal execution evidence, skips both completed and failed executions, and completes the run only after every expected report evaluator has terminal evidence.
- [ ] Interruption after some report evaluators complete can resume on the same run, with later evaluators receiving the same evidence-contract semantics as earlier evaluators.
- [ ] Finalization claim acquisition, expiry, ownership checks, and release prevent competing workers from creating duplicate Report Evaluator Executions.
- [ ] Repeated finalization is idempotent, and any serialized or rendered aggregate report is treated and linked only as a derived export.
- [ ] Highest-level tests cover successful multi-case materialization, task and evaluator failures, typed payloads, partial finalization recovery, repeated invocation, unsupported contracts, tampered manifests or checkpoints, schema mismatch, and competing finalizers.

## Blocked by

- [Freeze an aggregate manifest over terminal case checkpoints](11-freeze-an-aggregate-manifest-over-terminal-checkpoints.md)
