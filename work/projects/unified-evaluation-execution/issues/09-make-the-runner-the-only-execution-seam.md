# Make the runner the only execution seam

Labels: completed

Closes inbox items EP-01 and EP-03 for the
[Unified Evaluation Execution Path](../PRD.md). The largest change in the project,
and deliberately last.

## What to build

There is one documented way to execute an evaluation. An author no longer has to
work out which of three entry points has the semantics they need, because two of
them are gone.

`EvaluationRunner.run` requires a Resolved Evaluation Plan. There is no plan-less
branch, so no run can silently derive its own evaluator assignments. Persistence
is decided when constructing the Evaluation Ledger rather than by an argument to
the call; its named in-memory constructor creates no database file.

`EvaluationSuite.execute` is removed. `EvaluationSuite` goes back to being a
definition: it answers questions about its Configured Evaluators, report
evaluators, metrics, Evaluation Requirement Bindings, and Evaluation Task
Contract, and it executes nothing. Its seven existing call sites move to a runner
constructed over an in-memory Evaluation Ledger; their assertions should survive the
move, and any that does not is a semantic change worth surfacing rather than
quietly accommodating.

`EvaluationEngine` survives as the internal case-execution mechanism driving
`pydantic_evals` but is no longer a public entry point.

Redundant case validation is removed from evaluator resolution and from durable
execution. Validation happens once, at preflight.

## Acceptance criteria

- [x] `EvaluationRunner.run` requires a Resolved Evaluation Plan and has no plan-less branch.
- [x] Persistence is determined by the Evaluation Ledger's construction, not by an argument to the run call.
- [x] `EvaluationSuite.execute` is removed.
- [x] `EvaluationSuite` retains its definition responsibilities: resolving Configured Evaluators, exposing report evaluators, metrics, Evaluation Requirement Bindings, and its Evaluation Task Contract.
- [x] All seven former `EvaluationSuite.execute` call sites execute through a runner over an in-memory Evaluation Ledger, with their original assertions intact.
- [x] Any assertion that could not survive the migration unchanged is called out explicitly as a semantic change rather than silently rewritten.
- [x] `EvaluationEngine` is no longer exported as a public entry point.
- [x] A happy-path test of plan-driven execution exists, closing the gap where the engine was covered only by a task-binding rejection test.
- [x] Redundant case validation is removed from evaluator resolution and from durable execution.
- [x] A retry run manifests exactly the Resolved Evaluation Plan it is given and never narrows to its predecessor's non-terminal cases.
- [x] The existing test that all execution entry points reject a mismatched Task Binding contract is updated to the single remaining seam and still passes, per ADR 0007.
- [x] The full deterministic test suite passes.

## Surfaced semantic changes

- Runner-materialized case evidence addresses assertions by the authored
  Configured Evaluator name, not the evaluator implementation class name.
- Free-form report-evaluator `ScalarResult` analyses are not canonical checkpoint
  evidence. Migrated tests assert persisted report-evaluator completion (or the
  evaluator's recorded invocation) instead; declared metric observations remain
  the durable report-output contract.
- Incompatible authored cases now fail during preflight, before a Resolved
  Evaluation Plan exists, rather than at an execution entry point.
- A retry no longer narrows to its predecessor's PENDING and CANCELLED cases; it
  executes the whole plan it is given. This corrects a defect rather than
  trading one behaviour for another. An Evaluation Run measures its whole
  caseload at one moment, so per CONTEXT.md "incomplete case execution requires
  a distinct linked retry, while incomplete report evaluation may resume as
  Evaluation Finalization on the same run" — resumption is reserved for
  finalization, and narrowing had made a retry resume case execution instead.
  `retry_of_run_id` is provenance linking one run to its predecessor, not an
  instruction to pick up where that run stopped. A caller who genuinely wants a
  narrower caseload preflights a narrower plan, which makes the narrowing
  explicit and visible in the frozen plan.

## Blocked by

- 07 — Evaluate reports the same way on both paths.
- 08 — Make durable execution consume the plan preflight produced.
