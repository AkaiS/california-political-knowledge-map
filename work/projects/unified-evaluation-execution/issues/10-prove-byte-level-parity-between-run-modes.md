# Prove byte-level parity between ephemeral and durable runs

Labels: ready-for-agent

Closes the [Unified Evaluation Execution Path](../PRD.md). This is the ticket that
turns structural parity from a claim into a check.

## What to build

An author can trust that an in-memory run tells them what the durable run will
produce, because a test proves the two produce the same Evaluation Report bytes.

The existing parity test compares a handful of semantic fields — one case's output
dump, the assertion names, some evaluator version tags. That was the strongest
claim available when the two paths were genuinely different code. Now that they
differ only in where evidence lands, the claim can be much stronger: run the same
Resolved Evaluation Plan through an ephemeral runner and a durable runner and
assert the canonical Evaluation Report bytes are identical.

Canonical report serialization also gets round-trip coverage it has never had.
It is untested today, which was tolerable while it sat on one path and is not now
that it is the shared basis for comparing both.

## Acceptance criteria

- [ ] A test runs one Resolved Evaluation Plan through both an ephemeral and a durable runner and asserts the canonical Evaluation Report bytes are identical.
- [ ] Parity is asserted over a plan with several Evaluation Cases and several evaluators, not a single trivial case.
- [ ] Parity holds for a run containing at least one Evaluation Case with no expected output.
- [ ] Parity holds for a run in which a report evaluator failed, so the equivalence covers recorded failures and not only the happy path.
- [ ] Canonical report serialization and deserialization are round-trip tested directly.
- [ ] The former field-by-field parity test is replaced by the byte-level test rather than kept alongside it.
- [ ] The full deterministic test suite passes, and the passing count is recorded so the project's before-and-after state is on record.

## Blocked by

- 09 — Make the runner the only execution seam.
