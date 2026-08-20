# Evaluate reports the same way on both paths

Labels: completed

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

The shared path keeps its fencing. Report evaluation stays inside the existing
claim-fenced Evaluation Finalization phase and remains replay-tolerant, per
ADR 0011 and ADR 0012.

The original statement that an ephemeral path ran without claims or heartbeats
is retracted. The buffer used an in-memory Evaluation Ledger rather than a
different store, and issues 12–14 removed the branch and restored unconditional
finalization fencing. Every evaluation now takes a finalization claim.

## Acceptance criteria

- [x] Report evaluators run after report materialization on the shared path.
- [x] One evaluator loop serves the shared path; there is no per-mode copy of report evaluation.
- [x] The `pydantic_evals` report-evaluator hook is no longer used for report evaluation.
- [x] The None-safe and deferred report-evaluator wrapper classes are deleted.
- [x] A report evaluator that raises is recorded as a failed execution and the run still produces an Evaluation Report, proven on the shared, claim-fenced path.
- [x] A report evaluator that returns nothing produces no observations and no error, proven on the shared path.
- [x] Durable report evaluation remains inside the claim-fenced Evaluation Finalization phase.
- [x] Durable Evaluation Finalization remains resumable after a report-evaluator failure, per ADR 0011.
- [x] Existing finalization claim, renewal, and fencing tests pass unmodified, per ADR 0012.
- ~~Ephemeral report evaluation runs without claims or heartbeats.~~ **Retracted:** there is one ledger-backed finalization path, and it always takes a claim; issues 12–14 removed the exception.
- [x] The full deterministic test suite passes.

## Blocked by

- 06 — Run an evaluation without a ledger, through an in-memory evidence sink.
