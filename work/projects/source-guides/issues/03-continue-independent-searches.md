# 03 Keep independent searches running across navigation

Labels: enhancement, ready-for-agent
Parent: [Source Guides spec](../PRD.md)

## What to build

Let several questions run independently while the voter switches guides or
closes the page. The local application owns execution, and a reopened running
guide reconnects to its saved status instead of starting another search.

## Acceptance criteria

- [ ] Submission returns the saved guide identity and attempt status promptly;
  work belongs to the application's lifespan rather than an HTTP response or
  browser connection.
- [ ] Two independent guides can progress without one displayed guide owning
  the other's execution. Preserve existing provider admission/resource limits;
  this does not require unlimited model concurrency.
- [ ] Switching guides, reloading, or disconnecting the browser leaves execution
  running while the local service remains active.
- [ ] List and detail views show persisted running and terminal status. Reopening
  reconnects to the current attempt without duplicate retrieval or model calls.
- [ ] Completion publishes content and retrieval information atomically, only
  for that guide's active attempt identity. An obsolete completion cannot
  overwrite another guide or a newer attempt.
- [ ] Closing the application is distinct from closing the browser. Restart
  recovery and explicit Retry are implemented by ticket 06.

## Blocked by

- [02 Save, browse, and reopen Source Guides](02-save-and-reopen-guides.md)

## Validation

At the application boundary, hold deterministic executions with explicit
events and prove independent progress, disconnect tolerance, status reconnection,
and guarded publication through visible outcomes in temporary real SQLite.
Avoid timing sleeps and assertions about private task registries. In the browser,
start multiple questions, switch views, close/reopen the page, and observe their
continued progress. Run required checks with uv, without a separate Chat Session
test seam.
