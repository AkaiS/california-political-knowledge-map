# Remove the durability branch from the executor

Labels: ready-for-agent

Part of the [Unified Evaluation Execution Path](../PRD.md). This is the ticket
that makes executing a Resolved Evaluation Plan mean one thing.

## What to build

Executing a Resolved Evaluation Plan performs the same work regardless of which
store the runner was constructed over.

Today it does not. The executor asks its store whether it is ephemeral and, when
it is, materializes the Evaluation Report, runs the report evaluators, and
completes the Evaluation Run inline — work that is otherwise Evaluation
Finalization's job. So the same call means "execute the cases" against one store
and "execute the cases and finish the whole run" against another. The PRD is
explicit that this is not how durability was supposed to be selected: it is a
property of the evidence sink, "not by an argument to `run` and not by a branch
inside the executor." The branch is that branch.

After this ticket, execution freezes case evidence and stops. Deriving the
Evaluation Report and running report evaluators belongs to Evaluation
Finalization, on every path. Callers that previously received a finished report
from execution alone finalize explicitly, exactly as durable callers already do.
The ephemerality flag both stores carry exists only to feed this branch and goes
with it.

This is the change that makes the two run modes structurally identical rather
than merely asserted to agree. It is worth landing on its own, before anything is
deleted, because it is the step that can be judged against the existing durable
test suite unmodified.

## Acceptance criteria

- [ ] The executor does not inspect its store to decide what work to perform.
- [ ] Executing a Resolved Evaluation Plan performs the identical sequence of operations over an in-memory store and over a file-backed Evaluation Ledger.
- [ ] Deriving the Evaluation Report and running report evaluators happens only in Evaluation Finalization, on every path.
- [ ] Every caller that previously obtained a completed Evaluation Run or report evaluator executions from execution alone obtains them through Evaluation Finalization.
- [ ] No ephemerality flag remains on either store, and nothing probes for one.
- [ ] Existing durable Evaluation Run, Evaluation Finalization, claim, and fencing tests pass unmodified.
- [ ] The full deterministic test suite passes.

## Blocked by

None — can start immediately.
