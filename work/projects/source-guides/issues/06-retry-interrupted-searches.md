# 06 Recover interrupted searches with explicit Retry

Labels: enhancement, completed
Parent: [Source Guides spec](../PRD.md)

## What to build

After the local service restarts, identify saved unfinished attempts as
interrupted. Let the voter explicitly retry an interrupted or failed attempt
for the same guide without losing previously saved reading.

## Acceptance criteria

- [x] Startup marks persisted unfinished local attempts interrupted instead
  of leaving them permanently running. It preserves questions, previous
  content, and last successful retrieval information.
- [x] Interrupted and failed guides offer Retry with a clear latest-attempt
  state. Retry creates a new execution identity for the same question and guide.
- [x] Retry follows the normal atomic publication rules. It preserves prior
  content while running or on failure; successful new content replaces it.
- [x] Restart, listing, opening, and reload never replay requests automatically.
  No checkpoint/resume mechanism is introduced.
- [x] Terminal completed, empty, Declined, and Deferred records remain terminal
  across restart. An obsolete attempt cannot publish over a retry.

## Blocked by

- [03 Keep independent searches running across navigation](03-continue-independent-searches.md)

## Validation

Use successive application instances over the same temporary real SQLite store
with deterministic injected work. Prove startup interruption, retained content,
no automatic calls, explicit Retry, and active-attempt publication guards through
public outcomes. In the browser, interrupt the local service during a search,
restart it, reopen the guide, and retry explicitly. Run required checks with uv;
do not add a separate Chat Session test seam.

## Comments

Completed after independent Standards and Spec review on 2026-10-09 UTC.
[Implementation validation](../validation/ticket-06.md) maps all five acceptance
criteria to controlled application and browser evidence.
[Review evidence](../validation/ticket-06-review.md) records both reports,
the accepted tracker-state finding, and final verification. The finding is
resolved by checking these criteria, applying the single `completed` state,
and advancing the authoritative work README frontier. No valid ticket 06
finding remains unresolved.
