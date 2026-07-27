# Evaluate Evaluation Cases that declare no expected output

Labels: ready-for-agent

Fixes the defect described in the [Unified Evaluation Execution Path](../PRD.md).
Independently valuable and independently shippable.

## What to build

An author can evaluate an operation whose correctness is judged by rubric rather
than by exact match. A run containing Evaluation Cases with no expected output
executes, checkpoints, and finalizes into an Evaluation Report.

Today such a run succeeds all the way through case execution and checkpointing
and then fails at finalization, discarding the expensive work, because report
case materialization validates the task's *actual* output against the *case's
expected-output* schema and raises when that schema is absent. Those are two
different things. An Evaluation Case's expected output is optional by design; the
Evaluation Task Contract's output schema is required and always present.

Materialization validates actual task output against the Evaluation Task
Contract's output schema, taken from the frozen Evaluation Suite. A case that
does declare an expected output continues to have that value validated against
its own declared expected-output schema — removing the conflation must not remove
real checking. A case that declares none proceeds without an expected output,
which is the ordinary supported condition.

## Acceptance criteria

- [ ] Report case materialization validates the task's actual output against the Evaluation Task Contract's output schema from the frozen Evaluation Suite.
- [ ] Materialization no longer treats a case's expected-output schema as the schema of the actual output.
- [ ] A missing expected-output schema does not raise during materialization.
- [ ] A case that declares an expected output still has that expected output validated against its declared expected-output schema, at authoring time as it is today.
- [ ] A case whose expected output does not match its declared expected-output schema is still rejected, proven by a test.
- [ ] A run whose cases all lack expected outputs completes execution, checkpointing, and finalization, and yields an Evaluation Report.
- [ ] A single run mixing cases with and without expected outputs completes and yields a report covering all of them.
- [ ] The Evaluation Report derived for a case without an expected output is well-formed and omits the expected output rather than substituting a placeholder.
- [ ] The evidence contract version remains 1.
- [ ] The full deterministic test suite passes.

## Blocked by

None — can start immediately.
