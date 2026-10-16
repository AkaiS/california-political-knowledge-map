# 02 Project Chat Session stage failures

Labels: completed

## Parent

[Source Guide projection](../PRD.md)

## What to build

When a Chat Session fails during assessment, retrieval or guidance, the failed
Source Guide comes from the projection. That guide includes the stage's reader
message, its disclosure and any Deferred explanation.

- The web application's execution code hands the stage failure, named by the
  Chat Session, to the projection instead of building the guide by hand.
- The chat evaluation task records the same failed Source Guide a reader would
  have seen. It keeps its existing failure record for operational diagnostics
  and historical comparability.

## Acceptance criteria

- [x] The Chat Session outcome includes a stage failure. It names the
      assessment, retrieval or guidance stage and carries the assessment when
      one exists.
- [x] Projection tests cover each stage, with and without a Deferred
      assessment. They assert status, message, disclosure kinds and the
      retained Deferred explanation.
- [x] The web application's execution code contains no stage-to-status,
      message or disclosure rules.
- [x] For a failure within the Chat Session, the chat evaluation task records
      the Source Guide the projection produces for that stage. Its existing
      failure record keeps the same fields and stage names.
- [x] Failures outside the Chat Session (startup, rendering, cleanup) keep
      their current evaluation behaviour.
- [x] Existing HTTP failure, coverage and update tests pass unchanged.

## Blocked by

- [01 Project Retrieval Answers and assessments through one outcome interface](01-project-answers-and-assessments.md)
