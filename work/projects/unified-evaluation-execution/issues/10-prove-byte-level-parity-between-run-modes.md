# Prove byte-level parity between ephemeral and durable runs

Labels: completed

Closes the [Unified Evaluation Execution Path](../PRD.md). This is the ticket that
turns structural parity from a claim into a check.

> **Parity portion superseded by issues 14 and 15.** Issue 14 removed the second
> store façade, making parity structural, and issue 15 deleted the resulting
> self-comparison.
>
> **Fully retracted 2026-07-30.** The round-trip coverage was the last surviving
> claim of this ticket, on the reasoning that it tested serialization independently
> of parity. That reasoning does not hold: the serializer it tested exists only to
> support the retracted parity comparison, and ADR 0011 forbids the persisted
> report blob it produces. Nothing of this ticket survives.

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

- ~~A test runs one Resolved Evaluation Plan through both an ephemeral and a durable runner and asserts the canonical Evaluation Report bytes are identical.~~ **Retracted:** issue 15 deleted this test after issue 14 reduced it to comparing one path with itself.
- ~~Parity is asserted over a plan with several Evaluation Cases and several evaluators, not a single trivial case.~~ **Retracted:** there are no two implementations whose parity can diverge.
- ~~Parity holds for a run containing at least one Evaluation Case with no expected output.~~ **Retracted as a parity criterion:** expected-output coverage remains on the shared path.
- ~~Parity holds for a run in which a report evaluator failed, so the equivalence covers recorded failures and not only the happy path.~~ **Retracted as a parity criterion:** evaluator-failure coverage remains on the shared, claim-fenced path.
- ~~Canonical report serialization and deserialization are round-trip tested directly.~~ **Retracted (2026-07-30):** `canonical_report_bytes` and `report_from_bytes` had no caller on `main` before this project and gained none during it. They serialize and reload complete `ReportCase` values as a standalone blob — the ADR 0005 aggregate-report blob that [ADR 0011](../../../docs/adr/0011-freeze-aggregate-manifests-over-terminal-checkpoints.md) supersedes, which holds that the manifest carries "no ... complete ReportCase values" and the report is "a derived projection, never an independently authoritative persisted blob." Both functions and the round-trip test are deleted.
- ~~The former field-by-field parity test is replaced by the byte-level test rather than kept alongside it.~~ **Retracted:** issue 15 removed the byte-level replacement because its subject no longer exists.
- [x] The full deterministic test suite passes, and the passing count is recorded so the project's before-and-after state is on record.

## Verification

- Before: `453 passed`, recorded in `work/README.md` on 2026-07-24.
- After: `482 passed` on 2026-07-27 (`uv run pytest -q`).

## Blocked by

- 09 — Make the runner the only execution seam.
