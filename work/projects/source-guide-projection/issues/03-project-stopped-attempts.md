# 03 Project stopped attempts

Labels: completed

## Parent

[Source Guide projection](../PRD.md)

## What to build

Cancelled, interrupted and time-limited attempts get their Source Guides from the
projection. That covers:

- cancellation by the reader;
- the public execution time limit;
- task cancellation during shutdown;
- startup recovery of unfinished attempts.

Each reader message is defined once. This removes the interrupted message that
is currently duplicated between the web application and the Source Guide store.

## Acceptance criteria

- [x] The Chat Session outcome includes stopped attempts: cancelled,
      interrupted and exceeded time limit.
- [x] Projection tests assert the status and message for each stopped outcome.
- [x] The cancel route, deadline handling, shutdown cancellation and startup
      recovery build their guides only through the projection.
- [x] The interrupted message has one definition.
- [x] Existing cancellation, recovery, execution and public deployment HTTP
      tests pass unchanged.

## Blocked by

- [01 Project Retrieval Answers and assessments through one outcome interface](01-project-answers-and-assessments.md)
