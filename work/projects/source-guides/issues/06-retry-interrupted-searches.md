# 06 Recover interrupted searches with explicit Retry

Labels: enhancement, ready-for-agent
Parent: [Source Guides spec](../PRD.md)

## What to build

After the local service restarts, identify saved unfinished attempts as
interrupted. Let the voter explicitly retry an interrupted or failed attempt
for the same guide without losing previously saved reading.

## Acceptance criteria

- [ ] Startup marks persisted unfinished local attempts interrupted instead
  of leaving them permanently running. It preserves questions, previous
  content, and last successful retrieval information.
- [ ] Interrupted and failed guides offer Retry with a clear latest-attempt
  state. Retry creates a new execution identity for the same question and guide.
- [ ] Retry follows the normal atomic publication rules. It preserves prior
  content while running or on failure; successful new content replaces it.
- [ ] Restart, listing, opening, and reload never replay requests automatically.
  No checkpoint/resume mechanism is introduced.
- [ ] Terminal completed, empty, Declined, and Deferred records remain terminal
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
