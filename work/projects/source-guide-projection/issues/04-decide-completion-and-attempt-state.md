# 04 Decide completion, attempt state and promotion in the projection

Labels: completed

## Parent

[Source Guide projection](../PRD.md)

## What to build

The projection is the only module that decides search completion. It also keeps
the search scope recorded when an attempt started. The Source Guide store keeps
its rule that only the latest running attempt can finish, but no longer computes
reader-facing values.

The projection module also owns two mappings from a terminal guide status:

- to the persisted attempt state;
- to whether the outcome replaces the saved reading.

Search completion reads the same in the saved guide and the latest attempt, and
failed or stopped attempts keep the scope the reader saw at submission.

## Acceptance criteria

- [x] The projection receives the attempt's search scope and sets completion
      for every terminal outcome:
  - [x] failed statuses give "failed";
  - [x] cancelled and interrupted keep their names;
  - [x] Declined and needs edit give "not_searched";
  - [x] a partial search gives "partial";
  - [x] otherwise "completed".
- [x] The projection module owns the status-to-attempt-state mapping and the
      rule that completed and empty outcomes replace the saved reading. The
      store applies both inside its existing conditional update.
- [x] The store no longer recomputes completion or falls back to the running
      attempt's search details.
- [x] Helpers that existed only for hand-built guides are internal to the
      projection module or deleted.
- [x] Projection tests cover completion, attempt state and promotion for every
      terminal status, and scope retention for failed and stopped outcomes.
- [x] Existing coverage, update, recovery, cancellation and store HTTP tests
      pass unchanged.

## Blocked by

- [02 Project Chat Session stage failures](02-project-stage-failures.md)
- [03 Project stopped attempts](03-project-stopped-attempts.md)

## Comments

- 2026-10-16, whole-sequence review of tickets 01-04: `guide_collections`
  stays public. The PRD named it among helpers that become internal, but after
  this sequence no caller uses it to hand-build a guide. The web application
  and the chat evaluation task call it only to record the search scope at
  submission, which the projection receives as an argument. The helpers
  criterion above holds for that reason.
- 2026-10-16, same review: chat evaluation guides for Declined and needs-edit
  assessments now carry `search_details` with the submission scope and
  `not_searched`, matching the guide the web application saves (user story 28).
  Reports recorded before this change have `null` there. The report fields and
  their meaning are unchanged.
