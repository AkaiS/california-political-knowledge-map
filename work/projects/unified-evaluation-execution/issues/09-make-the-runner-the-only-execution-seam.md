# Make the runner the only execution seam

Labels: ready-for-agent

Closes inbox items EP-01 and EP-03 for the
[Unified Evaluation Execution Path](../PRD.md). The largest change in the project,
and deliberately last.

## What to build

There is one documented way to execute an evaluation. An author no longer has to
work out which of three entry points has the semantics they need, because two of
them are gone.

`EvaluationRunner.run` requires a Resolved Evaluation Plan. There is no plan-less
branch, so no run can silently derive its own evaluator assignments. Durability
remains a property of the evidence sink the runner was constructed with, decided
at construction rather than by an argument to the call.

`EvaluationSuite.execute` is removed. `EvaluationSuite` goes back to being a
definition: it answers questions about its Configured Evaluators, report
evaluators, metrics, Evaluation Requirement Bindings, and Evaluation Task
Contract, and it executes nothing. Its seven existing call sites move to a runner
constructed over an in-memory evidence sink; their assertions should survive the
move, and any that does not is a semantic change worth surfacing rather than
quietly accommodating.

`EvaluationEngine` survives as the internal case-execution mechanism driving
`pydantic_evals` but is no longer a public entry point.

Redundant case validation is removed from evaluator resolution and from durable
execution. Validation happens once, at preflight.

## Acceptance criteria

- [ ] `EvaluationRunner.run` requires a Resolved Evaluation Plan and has no plan-less branch.
- [ ] Durability is determined by the evidence sink the runner was constructed over, not by an argument to the run call.
- [ ] `EvaluationSuite.execute` is removed.
- [ ] `EvaluationSuite` retains its definition responsibilities: resolving Configured Evaluators, exposing report evaluators, metrics, Evaluation Requirement Bindings, and its Evaluation Task Contract.
- [ ] All seven former `EvaluationSuite.execute` call sites execute through a runner over an in-memory evidence sink, with their original assertions intact.
- [ ] Any assertion that could not survive the migration unchanged is called out explicitly as a semantic change rather than silently rewritten.
- [ ] `EvaluationEngine` is no longer exported as a public entry point.
- [ ] A happy-path test of plan-driven execution exists, closing the gap where the engine was covered only by a task-binding rejection test.
- [ ] Redundant case validation is removed from evaluator resolution and from durable execution.
- [ ] The existing test that all execution entry points reject a mismatched Task Binding contract is updated to the single remaining seam and still passes, per ADR 0007.
- [ ] The full deterministic test suite passes.

## Blocked by

- 07 — Evaluate reports the same way on both paths.
- 08 — Make durable execution consume the plan preflight produced.
