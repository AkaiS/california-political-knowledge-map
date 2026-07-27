# Evaluate reports the same way on both paths

Labels: ready-for-agent

Part of the [Unified Evaluation Execution Path](../PRD.md).

## What to build

A report evaluator behaves identically whether the run was durable or ephemeral.
Today it does not: in memory it runs through the `pydantic_evals`
report-evaluator hook wrapped in two compatibility shims, and durably it runs in a
claim-fenced finalization phase that iterates evaluators by hand. An author cannot
predict from an in-memory run how a judge will behave durably.

Report evaluators run after report materialization on both paths, against a
materialized Evaluation Report, using one evaluator loop. The framework's
report-evaluator hook is not used, and the two wrapper classes that existed only
to accommodate it are deleted.

Both paths adopt the current durable semantics. A report evaluator that raises is
recorded as a failed execution and the run still produces an Evaluation Report —
one bad judge does not destroy the whole report. A report evaluator that returns
nothing produces no observations and is not an error, so conditional evaluators
remain expressible.

The durable path keeps its fencing. Report evaluation stays inside the existing
claim-fenced Evaluation Finalization phase and remains replay-tolerant, per
ADR 0011 and ADR 0012. The ephemeral path runs the same evaluator loop without
claims or heartbeats, because there is no contention to fence.

## Acceptance criteria

- [ ] Report evaluators run after report materialization on both the durable and the ephemeral path.
- [ ] One evaluator loop serves both paths; there is no per-path copy of report evaluation.
- [ ] The `pydantic_evals` report-evaluator hook is no longer used for report evaluation.
- [ ] The None-safe and deferred report-evaluator wrapper classes are deleted.
- [ ] A report evaluator that raises is recorded as a failed execution and the run still produces an Evaluation Report, on both paths, proven by a test on each.
- [ ] A report evaluator that returns nothing produces no observations and no error, on both paths, proven by a test on each.
- [ ] Durable report evaluation remains inside the claim-fenced Evaluation Finalization phase.
- [ ] Durable Evaluation Finalization remains resumable after a report-evaluator failure, per ADR 0011.
- [ ] Existing finalization claim, renewal, and fencing tests pass unmodified, per ADR 0012.
- [ ] Ephemeral report evaluation runs without claims or heartbeats.
- [ ] The full deterministic test suite passes.

## Blocked by

- 06 — Run an evaluation without a ledger, through an in-memory evidence sink.
