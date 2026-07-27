# Make durable execution consume the plan preflight produced

Labels: ready-for-agent

Closes inbox items EP-04 and EP-05 for the
[Unified Evaluation Execution Path](../PRD.md).

## What to build

An operator who inspects a Resolved Evaluation Plan before a run can prove
afterwards that the plan they inspected is the plan that executed. Today durable
execution independently derives its own evaluator assignments and accepts
duplicated plan-derived fields that it then revalidates, so the plan preflight
returned is advisory rather than authoritative.

Durable execution consumes the Resolved Evaluation Plan preflight produced. It
does not rederive evaluator assignments from Suite-wide case evaluators, case
Evaluation Requirements, and requirement bindings — that derivation happened once,
in preflight, and its result is frozen. Per ADR 0005 requirements are resolved
before execution; this makes the resolution binding rather than repeated.

The Evaluation Run is constructed from the plan rather than from separately passed
plan-derived arguments. The plan recorded on the run is byte-identical to the plan
preflight returned.

## Acceptance criteria

- [ ] Durable execution consumes the Resolved Evaluation Plan produced by preflight and does not derive evaluator assignments itself.
- [ ] The Evaluation Run is constructed from the plan rather than from duplicated plan-derived fields passed alongside it.
- [ ] Plan-derived arguments that the plan already carries are removed from the durable execution entry point rather than accepted and revalidated.
- [ ] The plan persisted on the Evaluation Run has canonical JSON byte-identical to the plan preflight returned, proven by a test.
- [ ] Overlapping evaluator assignments remain deduplicated into one application while retaining which Evaluation Requirements each application satisfies, per the Resolved Evaluation Plan's definition.
- [ ] Requirement resolution happens once, before execution, per ADR 0005.
- [ ] Existing tests asserting on persisted plan canonical JSON and plan stability still pass.
- [ ] Existing durable runner tests pass, modified only where they passed now-removed duplicated arguments.
- [ ] The full deterministic test suite passes.

## Blocked by

- 02 — Report every preflight compatibility issue in one raise.
