# Delete the in-memory evidence buffer and the unused evidence-source protocol

Labels: completed

Part of the [Unified Evaluation Execution Path](../PRD.md). This is the
subtraction the three preceding tickets make safe.

## What to build

An evaluation author drafting a suite still runs it against a handful of
Evaluation Cases with no database file on disk. They construct an Evaluation
Ledger that keeps its evidence in memory, through a named constructor that says
so, and everything else about the call is what it already was. There is one store
type, one execution path, and one derivation of the Evaluation Report.

The in-memory evidence buffer is deleted. It was never the second store the PRD
described: it wrapped an Evaluation Ledger over SQLite's in-memory transport and
forwarded every call to it, so what looked like a durable-versus-ephemeral
distinction was a connection-string difference the ledger already supported. Once
the executor stopped branching on it and the fencing waiver went away, what
remained of the type was a terminal-checkpoint accessor and a cleanup routine.
Keeping a second type, a second protocol, and a parity claim to describe a
difference that does not exist costs more than it explains.

The evidence-source protocol goes with it. It was introduced to make report
materialization sink-agnostic, and nothing ever read through it — it has no
consumers anywhere in the source or the tests.

Preserve the affordance, not the type. "Run this without persisting it" is a real
authoring intent and deserves to be sayable; it should be a named constructor on
the Evaluation Ledger rather than a bare connection string at every call site.

## Acceptance criteria

- [x] A named constructor on the Evaluation Ledger produces a ledger that persists nothing to a database file, so the authoring intent is expressible without a magic connection string.
- [x] An evaluation runs end to end over that ledger and produces an Evaluation Report, with no database file created on disk.
- [x] The in-memory evidence buffer type no longer exists and is no longer exported from the evaluation package.
- [x] The evidence-source protocol no longer exists and is no longer exported.
- [x] Every test that constructed the buffer constructs an in-memory Evaluation Ledger instead.
- [x] The terminal-checkpoint accessor the buffer offered remains available to the tests that used it, without a production type existing solely to provide it.
- [x] Evidence validation, Evaluation Checkpoint identity, and content hashing are unchanged; evidence produced in memory stays indistinguishable in shape from persisted evidence.
- [x] The Evaluation Report remains a derived projection, per ADR 0011.
- [x] The full deterministic test suite passes.

## Verification

- `493 passed` on 2026-07-29 (`uv run pytest -q`).

## Blocked by

- 11 — Own temporary artifact cleanup in the Evaluation Ledger. Without it, deleting the buffer leaks a temporary directory per run.
- 12 — Remove the durability branch from the executor.
- 13 — Restore the unconditional finalization claim fence.
