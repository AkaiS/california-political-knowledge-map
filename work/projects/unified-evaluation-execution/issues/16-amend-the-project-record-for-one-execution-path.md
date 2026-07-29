# Amend the project record for a single execution path

Labels: ready-for-agent

Part of the [Unified Evaluation Execution Path](../PRD.md). The record should say
what the code does, and should retract what it no longer claims.

## What to build

A reader of this project's PRD and issues learns that the project ended with one
execution path and one store, and learns why the two-sink design it originally
specified was abandoned. Nothing is left checked-off against deleted code.

Three corrections matter most. The PRD asserts that the ephemeral sink "is not a
second façade over the same store, it is a different store entirely" — that was
never true of the implementation, which wrapped an Evaluation Ledger over
SQLite's in-memory transport and forwarded to it. The user stories describing a
second evidence sink implementation, a sink-agnostic evidence source, and
byte-level parity between two run modes describe work that is being deliberately
removed, not work that was missed. And the criterion that ephemeral report
evaluation runs without claims or heartbeats no longer holds: with one store,
Evaluation Finalization takes a claim on every path.

Retract, do not delete. A reader should be able to see what was originally
intended and why it was reversed, because the reasoning — that the abstraction
was describing a difference that did not exist — is the useful part.

Structural parity is now a stronger claim than the PRD originally made, and the
record should say so: the two run modes cannot diverge because there is only one
of them, so parity is not a property any test needs to assert.

No glossary work is required. The terms introduced alongside the buffer never
entered `CONTEXT.md`, and with the buffer gone they do not need to.

## Acceptance criteria

- [ ] The PRD no longer claims the ephemeral sink is a different store from the Evaluation Ledger.
- [ ] The user stories describing a second evidence sink implementation, a sink-agnostic evidence source, and running without a ledger are marked retracted, each with its reason.
- [ ] The user story and testing decision requiring byte-level parity between run modes are marked retracted, and the record states that parity is now structural because there is one execution path.
- [ ] Issue 06 is marked superseded and names the tickets that replaced it.
- [ ] Issue 07's criterion that ephemeral report evaluation runs without claims or heartbeats is retracted.
- [ ] Issue 05 records that the evidence sink protocol survives for the engine's checkpoint sink, while the two-implementations justification does not.
- [ ] Retractions state the reasoning, so a reader can see what was intended and why it was reversed.
- [ ] `work/README.md` reflects the project's current issue set.
- [ ] No new `CONTEXT.md` glossary entries are introduced.

## Blocked by

- 14 — Delete the in-memory evidence buffer and the unused evidence-source protocol.
