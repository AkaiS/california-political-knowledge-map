# Declare the full evidence sink protocol

Labels: ready-for-agent

Prefactor for the [Unified Evaluation Execution Path](../PRD.md). No substitutable
sink is possible while part of the contract is undeclared.

## What to build

Every method the executor calls on its evidence sink is part of the sink's
declared contract, so an implementation can be checked statically and swapped
wholesale for another. Today three of them are not: task-outcome recording, case
lifecycle notification, and partial report-evidence checkpointing are reached for
dynamically at the call site, which means a sink can appear to satisfy the
protocol while silently lacking behaviour the executor depends on.

Those three move onto the declared protocol. The executor calls them directly
rather than probing for them. The durable, ledger-backed sink implements the
whole protocol and its behaviour is unchanged by this ticket — this is a
declaration change, not a semantic one.

## Acceptance criteria

- [ ] Task-outcome recording is a declared method on the evidence sink protocol.
- [ ] Case lifecycle notification is a declared method on the evidence sink protocol.
- [ ] Partial report-evidence checkpointing is a declared method on the evidence sink protocol.
- [ ] The executor calls each of these directly; no dynamic attribute probing for sink methods remains.
- [ ] The durable, ledger-backed sink implements every method on the protocol.
- [ ] An object missing any protocol method is rejected as a sink rather than silently accepted.
- [ ] Durable Evaluation Run behaviour, recorded Evaluation Checkpoints, and Evaluation Report content are unchanged by this ticket.
- [ ] Existing durable runner and ledger tests pass unmodified.
- [ ] The full deterministic test suite passes.

## Blocked by

None — can start immediately.
