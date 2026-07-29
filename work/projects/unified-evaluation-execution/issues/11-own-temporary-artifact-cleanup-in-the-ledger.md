# Own temporary artifact cleanup in the Evaluation Ledger

Labels: ready-for-agent

Part of the [Unified Evaluation Execution Path](../PRD.md). A prefactor: it makes
the buffer removable without leaking, so the deletion that follows is a pure
subtraction.

## What to build

An Evaluation Ledger constructed without a database file creates a temporary
content-addressed artifact area for itself. Today nothing in the ledger removes
that area — the in-memory evidence buffer does it, by reaching past the ledger's
public surface to find where the ledger put it. That is backwards: the ledger
made the directory, so the ledger should clean it up, and no wrapper should need
to know the directory exists.

After this ticket, closing a ledger that created its own temporary artifact area
removes it. A ledger constructed over a caller-supplied database file leaves that
file's artifact directory alone — it is the caller's, not the ledger's, and
deleting it would destroy content-addressed evidence the caller still owns. The
distinction is who created the directory, not whether the database is in memory.

The in-memory evidence buffer stops removing the area and stops reading the
ledger's internals. It keeps working exactly as it does now; this ticket changes
where the responsibility lives, not what an author observes.

## Acceptance criteria

- [ ] An Evaluation Ledger that created its own temporary artifact area removes that area when it is closed.
- [ ] An Evaluation Ledger constructed over a caller-supplied database file leaves that database's artifact directory in place when it is closed.
- [ ] The in-memory evidence buffer no longer removes the artifact area and no longer reads the ledger's private state.
- [ ] Closing a ledger twice, or closing both the buffer and the ledger it wraps, does not raise.
- [ ] No temporary artifact directories survive a full run of the deterministic suite.
- [ ] Durable Evaluation Run and Evaluation Finalization behaviour is unchanged; existing tests pass unmodified.
- [ ] The full deterministic test suite passes.

## Blocked by

None — can start immediately.
