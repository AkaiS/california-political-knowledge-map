# Collapse the redundant run-mode test pairs

Labels: completed

Part of the [Unified Evaluation Execution Path](../PRD.md). The suite stops
asserting that one code path agrees with itself.

## What to build

Several tests exist to compare an ephemeral run against a durable one, or to
substitute one evidence sink for another. Once there is a single store type and a
single execution path, those tests assert that a thing equals itself: they pass
unconditionally, and they would keep passing if the behaviour they name broke.
That is worse than no coverage, because it reads like protection.

This ticket removes exactly those, keeps everything that still describes
behaviour, and renames the survivors that name a type which no longer exists. The
disposition of every affected test is decided here rather than left to judgement
at pickup — the reasoning is in this project's review history and should not be
re-derived.

Two things worth stating plainly, because they are easy to get wrong. Canonical
report serialization round-tripping was added by this project and is **kept**: it
was asked for independently of parity and still covers real behaviour on the
shared path. *(Reversed 2026-07-30 — see the criterion below; the serializer has
no caller.)* And where an ephemeral test and a durable test of the same
behaviour become duplicates, the surviving test is the durable one, because it
exercises the claim-fenced path as well.

Expect the suite to get smaller. That is the intended outcome, not a regression.

## Acceptance criteria

- [x] The test asserting that ephemeral and durable runs produce identical canonical report bytes is deleted; its subject no longer exists.
- ~~The test asserting that canonical report serialization round-trips is kept unchanged.~~ **Superseded (2026-07-30):** the test was deleted along with `canonical_report_bytes` and `report_from_bytes`. See issue 10 for the reasoning — the serializer has no caller and contradicts ADR 0011. The judgement recorded below that this test "covers real behaviour on the shared path" was wrong: it covered a function no path calls.
- [x] The test asserting that substituting in-memory evidence preserves materialized case evidence is deleted; nothing is being substituted.
- [x] The test asserting that in-memory and durable evidence reject the same invalid checkpoint is collapsed to a single case over one store.
- [x] The ephemeral and durable tests of a report evaluator that raises are merged into one, retaining the durable variant.
- [x] The ephemeral and durable tests of a report evaluator that returns nothing are merged into one, retaining the durable variant.
- [x] The test covering report materialization from in-memory evidence is renamed to describe the behaviour rather than the deleted type, and keeps its assertions.
- [x] The test covering retention of content-addressed terminal checkpoints is renamed on the same basis, and keeps its assertions.
- [x] No remaining test name refers to an evidence buffer, an ephemeral sink, or a durable-versus-ephemeral distinction.
- [x] Coverage of report evaluator failure, report evaluators returning nothing, invalid checkpoint rejection, and terminal checkpoint retention is retained.
- [x] The full deterministic test suite passes.

## Verification

- `489 passed` on 2026-07-29 (`uv run pytest -q`).
- `490 passed` on 2026-07-30 after the review corrections to issues 10 and 12
  (`uv run pytest -q`). The intervening rise to 491 came from the preflight,
  plan-integrity, and retry commits `83ded04`, `1632250`, `92ec393`, and
  `2fe91d0`; the drop to 490 is the deleted canonical round-trip test.
- Four fewer than the `493 passed` recorded by issue 14, accounted for by the
  pair collapses above: the byte-parity test and the in-memory evidence
  substitution test were deleted with their subjects, and two ephemeral/durable
  report-evaluator pairs were each merged into their durable variant.

## Blocked by

- 14 — Delete the in-memory evidence buffer and the unused evidence-source protocol.
