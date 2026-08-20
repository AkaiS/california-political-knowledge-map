# Run an evaluation without a ledger, through an in-memory evidence sink

Labels: completed

Part of the [Unified Evaluation Execution Path](../PRD.md). This is the ticket that
makes durability a property of the sink rather than a branch in the executor.

> **Superseded by issues 12–15.** Issue 12 removed the durability branch, issue
> 13 restored finalization claims on every path, issue 14 deleted the buffer and
> replaced it with the Evaluation Ledger's named in-memory constructor, and
> issue 15 removed tests that compared the shared path with itself. The
> no-database-file authoring affordance remains, but the claimed ledger-free
> execution and second store never existed: the buffer wrapped and forwarded to
> an in-memory Evaluation Ledger.

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

The original criteria are retained below as history, but no criterion remains
checked off against the buffer or evidence-source protocol deleted by issue 14.
The named in-memory ledger constructor preserves the useful authoring outcome.

- ~~An in-memory evidence sink implements the full evidence sink protocol.~~ **Retracted:** the buffer was a ledger façade, not an independent implementation.
- ~~A runner constructed over the in-memory sink executes a Resolved Evaluation Plan and produces an Evaluation Report without an Evaluation Ledger and without creating a database file.~~ **Retracted:** execution always used a ledger; issue 14 preserved only the no-file outcome.
- ~~The in-memory sink validates evidence with the same validation the durable sink applies; invalid evidence fails in both modes.~~ **Retracted:** the ledger performed validation on both SQLite transports.
- ~~The in-memory sink computes Evaluation Checkpoint identities and content hashes, so buffered evidence is indistinguishable in shape from persisted evidence.~~ **Retracted:** the ledger performed this work.
- ~~Report materialization reads through an evidence source abstraction satisfied by both the Evaluation Ledger and the in-memory buffer.~~ **Retracted:** the protocol had no consumers and was deleted by issue 14.
- ~~One materialization code path serves both modes; there is no ledger-specific and buffer-specific copy.~~ **Superseded:** one ledger and one execution path now make this structural.
- ~~The Evaluation Report remains a derived projection on both paths, per ADR 0011.~~ **Superseded:** the report remains a derived projection on the single path.
- ~~Substituting the in-memory sink for the durable sink in an otherwise identical run produces equivalent evidence, proven by a test.~~ **Retracted:** there is no second sink to substitute, and issue 15 deleted the self-comparison.
- ~~Durable Evaluation Run behaviour is unchanged; existing durable tests pass unmodified.~~ **Historical verification:** this was true when issue 06 landed, but it no longer describes two implementations.
- ~~The full deterministic test suite passes.~~ **Historical verification:** this recorded issue 06's completion, not a surviving buffer contract.

## Blocked by

- 03 — Evaluate Evaluation Cases that declare no expected output.
- 05 — Declare the full evidence sink protocol.
