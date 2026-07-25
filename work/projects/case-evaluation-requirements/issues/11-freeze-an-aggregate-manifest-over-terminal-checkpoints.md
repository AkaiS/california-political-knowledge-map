# Freeze an aggregate manifest over terminal case checkpoints

Labels: completed

## Parent

[Case Evaluation Requirements and Resumable Evaluation Execution](../PRD.md)

## What to build

Replace the duplicated serialized aggregate Evaluation Report with a content-addressed Frozen Aggregate Manifest. The manifest freezes the exact Evaluation Run, Suite, Resolved Evaluation Plan, Evaluation Task Contract, evidence-contract version, report-level provenance, and ordered identities and content hashes of the terminal case checkpoints that constitute the run. It contains references and integrity evidence, not copies of authored case payloads or complete ReportCase values.

Define the evidence-contract version as the durable semantic contract for both checkpoint interpretation and deterministic report-input materialization. The materializer and the installed Pydantic Evals version remain implementation details rather than independently persisted version authorities.

Atomically link the manifest artifact and move the run into finalization-pending only after every manifested case has matching terminal evidence. Update the domain language and architectural decision record so immutable definitions and checkpoints are authoritative, the Frozen Aggregate Manifest fixes their exact ordered composition, and Evaluation Report is a derived projection.

## Acceptance criteria

- [x] The Frozen Aggregate Manifest records the run identity, exact Suite and Resolved Evaluation Plan identities and hashes, exact Evaluation Task Contract identity or hash, evidence-contract version, report-level provenance, and the ordered manifest-entry, case-result, and checkpoint identities and content hashes.
- [x] Manifest bytes are canonical and content-addressed, so the same immutable run composition produces the same content identity.
- [x] The manifest contains no copied task inputs, expected outputs, actual outputs, metadata, evaluator results, or other complete ReportCase payloads.
- [x] A run with any pending, cancelled, missing, conflicting, or hash-mismatched case checkpoint cannot freeze its aggregate manifest or enter finalization-pending.
- [x] Registering the manifest artifact, linking it to the run, and transitioning the run to finalization-pending preserve the ledger's atomicity guarantees; a failure leaves no linked partial aggregate state.
- [x] Repeating manifest creation for the same frozen composition returns the same aggregate identity, while attempting to replace it with a different composition is rejected.
- [x] The evidence-contract version governs persisted evidence meaning and evaluator-visible report projection semantics; there is no separate persisted materializer version or Pydantic Evals compatibility version.
- [x] Domain documentation and a new or superseding architectural decision define the Frozen Aggregate Manifest and derived Evaluation Report model, replacing the earlier decision that a complete serialized report blob is authoritative.
- [x] Highest-level tests cover ordered multi-case identity, stable content addressing, terminal-evidence enforcement, tamper detection, atomic transition, and absence of duplicated case payloads.

## Blocked by

- [Materialize one typed ReportCase from an Evaluation Checkpoint](10-materialize-one-typed-report-case-from-a-checkpoint.md)
