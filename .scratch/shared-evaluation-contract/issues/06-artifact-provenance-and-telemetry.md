# 06. Query Complete Evaluation Artifact Provenance and Telemetry

Status: completed
Labels: ready-for-agent

## Parent

[Shared Evaluation Contract and Record Model](../PRD.md)

## What to build

Evaluation investigators can attach and query evidence at its smallest responsible producer: an authored definition revision, Evaluation Run, Evaluation Case Result, Case Evaluator Execution, or Report Evaluator Execution. Subject-specific artifact links preserve foreign-key integrity and use namespaced roles without generic polymorphic identifiers.

The ledger exposes separate read models for Evaluation Artifacts consumed by a run and artifacts produced by a run, including all case-result and evaluator evidence. Execution records also retain normalized Logfire trace/span identities where available, while the persisted ledger and serialized report remain authoritative for evaluation outcomes.

## Acceptance criteria

- [x] Each supported producer type has enforceable, subject-specific artifact links with extensible namespaced roles.
- [x] Task outputs, evaluator rationale, report analysis, and failure evidence attach to their smallest responsible producer rather than only to the enclosing run.
- [x] Consumed-artifact and produced-artifact read models are distinct; produced traversal includes run, report evaluator, Case Result, and case evaluator artifacts.
- [x] A single run query returns complete produced evidence without confusing inputs, rubrics, and generated outputs.
- [x] Evaluation execution records normalize available Logfire trace/span identities without creating a second telemetry configuration or requiring remote export in tests.
- [x] Artifact provenance, redacted-derivative lineage, and full run traversal are covered by deterministic SQLite contract tests.

## Blocked by

- [Preserve Incomplete, Failed, and Retried Evaluation Run Evidence](05-resilient-evaluation-run-lifecycle.md)
