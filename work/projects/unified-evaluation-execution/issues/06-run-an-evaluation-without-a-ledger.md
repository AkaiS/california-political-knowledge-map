# Run an evaluation without a ledger, through an in-memory evidence sink

Labels: completed

Part of the [Unified Evaluation Execution Path](../PRD.md). This is the ticket that
makes durability a property of the sink rather than a branch in the executor.

## What to build

An author drafting an Evaluation Suite can execute it against a handful of
Evaluation Cases and get back a full Evaluation Report with no Evaluation Ledger
and no database file on disk. They construct a runner over an in-memory evidence
buffer instead of over a ledger, and everything else about the call is identical.

The in-memory path is a write, not the absence of one. The executor projects each
completed case into canonical evidence, validates it, computes its Evaluation
Checkpoint identity and content hash, and hands it to the sink exactly as it does
today. The durable sink persists it; the buffer retains it. The distinction is
where evidence lands, never what evidence is produced.

Report materialization reads through an evidence source abstraction that both the
Evaluation Ledger and the in-memory buffer satisfy, so the Evaluation Report is
derived from canonical evidence by one code path in both modes. Per ADR 0011 the
report stays a derived projection and is never independently authoritative,
whichever sink produced the evidence it is derived from.

Report evaluation is out of scope here and is unified in the next ticket; this one
covers case execution, evidence, and report materialization.

## Acceptance criteria

- [x] An in-memory evidence sink implements the full evidence sink protocol.
- [x] A runner constructed over the in-memory sink executes a Resolved Evaluation Plan and produces an Evaluation Report without an Evaluation Ledger and without creating a database file.
- [x] The in-memory sink validates evidence with the same validation the durable sink applies; invalid evidence fails in both modes.
- [x] The in-memory sink computes Evaluation Checkpoint identities and content hashes, so buffered evidence is indistinguishable in shape from persisted evidence.
- [x] Report materialization reads through an evidence source abstraction satisfied by both the Evaluation Ledger and the in-memory buffer.
- [x] One materialization code path serves both modes; there is no ledger-specific and buffer-specific copy.
- [x] The Evaluation Report remains a derived projection on both paths, per ADR 0011.
- [x] Substituting the in-memory sink for the durable sink in an otherwise identical run produces equivalent evidence, proven by a test.
- [x] Durable Evaluation Run behaviour is unchanged; existing durable tests pass unmodified.
- [x] The full deterministic test suite passes.

## Blocked by

- 03 — Evaluate Evaluation Cases that declare no expected output.
- 05 — Declare the full evidence sink protocol.
