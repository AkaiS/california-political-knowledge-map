# Freeze the aggregate report and resume missing report work

Labels: completed

## Parent

[Case Evaluation Requirements and Resumable Evaluation Execution](../PRD.md)

## What to build

After every manifested case has terminal evidence, freeze the exact aggregate Pydantic Evaluation Report as the immutable input to an explicit Evaluation Finalization operation. Finalization resumes only missing report evaluator work on the same run, preserves each terminal outcome independently, and completes the workflow only when all expected report evidence is accounted for.

## Acceptance criteria

- [x] A run with any non-terminal manifested case cannot freeze its aggregate report or begin Evaluation Finalization.
- [x] The complete aggregate Pydantic Evaluation Report is canonically serialized exactly once after all cases become terminal.
- [x] Report bytes are registered as a content-addressed Evaluation Artifact outside relational rows, with stable identity, metadata, and a resolvable location.
- [x] Linking the report artifact and moving the run to an explicit finalization-pending state is atomic.
- [x] Evaluation Finalization is explicitly invoked by run identity and loads the frozen report artifact as its authoritative input.
- [x] Expected report evaluators are determined from the frozen Suite and Resolved Evaluation Plan rather than mutable authored state.
- [x] Only report evaluators lacking terminal execution evidence run; both successful and failed executions are skipped on later invocations.
- [x] Each new Report Evaluator Execution, its observations, issues, and artifact links commit atomically as it reaches terminal success or failure.
- [x] Report evaluator failure remains terminal negative evidence and is distinguishable from missing work.
- [x] Repeated finalization is idempotent, and the Evaluation Run becomes complete only after every expected report evaluator has terminal evidence.
- [x] Finalization is never resumed by an implicit background worker.

## Blocked by

- [Preserve multi-case progress and retry incomplete runs](06-preserve-multi-case-progress-and-retry-incomplete-runs.md)
