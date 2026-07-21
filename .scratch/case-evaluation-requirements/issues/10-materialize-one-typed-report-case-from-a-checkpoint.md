# Materialize one typed ReportCase from an Evaluation Checkpoint

Labels: ready-for-agent

## Parent

[Case Evaluation Requirements and Resumable Evaluation Execution](../PRD.md)

## What to build

Make one terminal Evaluation Checkpoint the immutable, authoritative source of run-specific evidence needed to materialize a semantically equivalent typed Pydantic Evals ReportCase. Reuse exact immutable authored definitions and frozen contracts rather than copying their payloads into the checkpoint. Extend the checkpoint evidence where necessary so materialization preserves task outcomes, evaluator result categories and explanations, evaluator failures, durations, attributes, artifact links, and trace provenance.

Values governed by an Evaluation Task Contract, Evaluation Case revision, Evaluation Metric Definition, or artifact contract use the schema reference owned by that immutable contract. Extensible values whose runtime type matters use a schema-tagged payload envelope. Schema resolution is allowlisted and verifies the exact schema identity, revision, and fingerprint; persisted data never selects a Python import path.

Treat the Configured Evaluator's revision and configuration fingerprint as its authoritative behavioral identity. Project that identity into Pydantic Evals evaluator-version metadata and emitted evaluation telemetry without creating a second independently managed version.

## Acceptance criteria

- [x] A terminal case checkpoint atomically commits the Evaluation Task Outcome, Case Evaluator Executions, evaluator results and failures, observations, issues, artifact links, durations, attributes, and trace provenance required to reconstruct that case's report semantics.
- [x] A terminal case checkpoint is immutable and idempotent: replaying the same checkpoint is harmless, while attempting to replace terminal evidence with different content is rejected.
- [x] Authored inputs, expected outputs, metadata, and their schema references remain owned by the exact immutable Evaluation Case and Evaluation Task Contract rather than being copied into run-specific checkpoint evidence.
- [x] Extensible fields accept canonical JSON values directly and require a schema-tagged envelope whenever a non-JSON runtime type must be preserved.
- [x] Schema-tagged payloads resolve only through an allowlisted registry, verify identity, revision, and fingerprint, and reject unknown or incompatible schemas without falling back to untyped dictionaries.
- [x] Structured metric observations use the schema owned by their exact Evaluation Metric Definition, and typed artifacts use their artifact-owned schema metadata when applicable.
- [x] Pydantic Evals Evaluation Results and failures receive an evaluator-version tag deterministically derived from the Configured Evaluator revision and configuration fingerprint, and the same value is available to evaluation telemetry such as Logfire.
- [x] A highest-level test checkpoints and reloads successful and failed cases, materializes typed ReportCase values, and proves equivalent task outcomes, evaluator result categories, values, reasons, failures, timings, attributes, artifact links, tracing, and concrete application-owned types.
- [x] A persistence or schema-resolution failure leaves no partial terminal checkpoint or producer evidence.

## Blocked by

None - can start immediately
