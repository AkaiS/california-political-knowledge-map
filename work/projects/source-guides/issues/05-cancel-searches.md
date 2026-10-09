# 05 Cancel searches without losing saved content

Labels: enhancement, completed
Parent: [Source Guides spec](../PRD.md)

## What to build

Let the voter cancel a running initial search or guide update. The cancelled
attempt stays visible, previous guide content stays readable, and other guides
continue independently.

## Acceptance criteria

- [x] A running guide exposes Cancel for its specific active attempt.
- [x] Cancellation persists a cancelled outcome and timing, retaining the
  submitted question and any previous content and retrieval information.
- [x] A late completion after cancellation cannot publish content, change the
  cancelled outcome, or replace previous content. Cancellation does not need
  to undo a provider request already issued.
- [x] Cancelling one attempt has no effect on another guide's running work.
- [x] Cancellation and completion races yield a consistent terminal outcome
  through the public operations, without partially published content.
- [x] Reopening restores the cancelled state and any retained content without
  automatic replay. Explicit Update guide can start another attempt.

## Blocked by

- [04 Update a guide or edit its question](04-update-and-edit-guides.md)

## Validation

Use application operations, temporary real SQLite, and event-controlled work
to test initial/update cancellation, isolated concurrent guides, and late
completion. Assert durable content/status rather than private cancellation
mechanisms. Verify Cancel, retained reading, and another guide's continued
progress in the browser. Run required checks with uv without independent
Chat Session tests.

## Comments

Completed after independent Standards and Spec review on 2026-10-09 UTC.
[Implementation validation](../validation/ticket-05.md) maps all six acceptance
criteria to controlled application and browser evidence.
[Review evidence](../validation/ticket-05-review.md) records both reports and
final verification. Neither axis found an issue. No valid ticket 05 finding
remains unresolved.
