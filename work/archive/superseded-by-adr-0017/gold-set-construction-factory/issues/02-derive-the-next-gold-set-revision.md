# Derive the next Gold Set revision by adding and removing cases

Labels: completed

Part of [Evaluation Gold Set Construction and Revisioning](../PRD.md). This is the
operation that makes a Gold Set's version number mean something.

## What to build

An evaluation author grows or trims an existing Evaluation Gold Set without
rebuilding it. They hand the factory the previous `EvaluationGoldSet`, the
Evaluation Cases to add, and the business identities to remove, and get back
revision N+1 under the same identity.

Every case that survives keeps exactly the split it had, read from the previous
revision's membership rather than recomputed, so a case that was in `held-out`
cannot migrate into a tuning loop and quietly contaminate every subsequent
held-out measurement. Only newly added cases are assigned, by the same
deterministic rule construction uses. The revision number is incremented for the
author so it cannot be reused or skipped, and a revision that neither adds nor
removes anything is refused because the revision history is supposed to record
real change.

Changing the Evaluation Task Contract is not a revision — it means the Gold Set
is evaluating a different operation, so per ADR 0006 it needs a new business
identity. The factory refuses a revision whose contract differs from its
predecessor's and says so, naming the remedy.

## Acceptance criteria

- [x] A revise operation in the Gold Set assembly module takes the previous `EvaluationGoldSet`, the Evaluation Cases to add, and the case identities to remove, and returns revision N+1 under the same identity.
- [x] Every surviving case keeps the split it held in the previous revision, taken from the previous membership rather than recomputed.
- [x] Newly added cases are assigned by the same deterministic rule construction uses.
- [x] Addition alone, removal alone, and both together each produce a correct revision, and surviving splits are preserved in all three.
- [x] The revision number is incremented by the operation and cannot be supplied by the caller.
- [x] A revision that neither adds nor removes anything is rejected.
- [x] A revision whose Evaluation Task Contract differs from its predecessor's is rejected, and the message directs the author to use a new business identity.
- [x] Newly added cases are validated against the Evaluation Task Contract with the same accumulating behaviour as construction.
- [x] The result is a frozen `EvaluationGoldSet`, and the operation performs no I/O and does not touch the Evaluation Ledger.
- [x] The full deterministic test suite passes.

## Blocked by

- 01 — Construct an Evaluation Gold Set with a validating factory.
