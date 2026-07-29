# Restore the unconditional finalization claim fence

Labels: completed

Part of the [Unified Evaluation Execution Path](../PRD.md). This ticket returns
ADR 0012's fencing guarantee to the Evaluation Ledger, where it belongs.

## What to build

Completing an Evaluation Run that is awaiting finalization always requires its
exact live finalization claim. There is no way to ask for the check to be
skipped.

Today there is. The execution store accepts a flag that waives the claim
requirement, and the in-memory evidence buffer overrides run completion to pass
it. ADR 0012 states that the Evaluation Ledger owns time and permits completion
only for the matching, still-live claim; a caller-supplied opt-out makes that
guarantee advisory, because the fence is only as strong as every caller's
decision to leave it on. The PRD placed this outside the project's scope
entirely — changing the claim, heartbeat, or fencing mechanics of Evaluation
Finalization was to be preserved as-is, not revised.

The waiver exists solely to serve the inline ephemeral completion removed in
ticket 12. Once execution no longer completes runs itself, the only caller
completing a run awaiting finalization is Evaluation Finalization, which always
holds a live claim. The parameter then has no remaining caller and the fence
becomes unconditional again with no other change.

This ticket carries the project's real risk. The existing claim, renewal,
heartbeat, and fencing tests are the gate: they must pass without modification.
If any of them needs editing to accommodate this change, stop — that means
durable fencing behaviour moved, which is not what this ticket is for.

## Acceptance criteria

- [x] Completing an Evaluation Run awaiting finalization always requires its exact live finalization claim.
- [x] No parameter, flag, or argument can waive that requirement.
- [x] No store, buffer, or wrapper overrides run completion to bypass fencing.
- [x] Existing finalization claim, renewal, heartbeat, expiry, and competing-worker tests pass unmodified, per ADR 0012.
- [x] Terminal-checkpoint recovery and resumable finalization behaviour are unchanged, per ADR 0011.
- [x] The full deterministic test suite passes.

## Blocked by

- 12 — Remove the durability branch from the executor. Until execution stops completing runs itself, the ephemeral path still needs the waiver.
