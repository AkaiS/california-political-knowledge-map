# 02 Save, browse, and reopen Source Guides

Labels: enhancement, completed
Parent: [Source Guides spec](../PRD.md)

## What to build

Save a Source Guide when the voter submits a question. Provide a saved-guide
list and detail view that restore the question, content, outcome, and retrieval
information after reload or local service restart, without running another search.

## Acceptance criteria

- [x] Submission saves a stable guide identity, complete question, and creation
  information before execution starts, including questions whose attempts fail
  or receive a request for editing, Declined, Deferred, or empty outcome.
- [x] Use existing SQLite infrastructure and transactions through a focused
  guide persistence interface. Save reader-facing content and disclosures so
  reopening does not require current graph hydration or regeneration.
- [x] Persist latest attempt identity, timing, and typed outcome separately
  from saved content and its last successful retrieval information. The model
  can retain completed, empty, failed, cancelled, and interrupted attempts and
  distinguish those from eligibility/coverage states.
- [x] The guide list identifies saved questions and their outcomes. Opening a
  guide restores its complete question, article reasons, source metadata,
  disclosures, and retrieval/status information.
- [x] Reload and a new application instance over the same store preserve
  completed and unsuccessful guides. Listing or opening never invokes retrieval
  or a model. No automatic expiry is introduced.
- [x] New question starts with empty input and carries no implicit question
  context from another guide. The application remains local and single-user.

## Blocked by

- [01 Submit an original question and read relevant articles](01-submit-original-questions.md)

## Validation

Use application HTTP/ASGI operations against temporary real SQLite with
deterministic retrieval/model substitutes. Restart the application against the
same store and prove saved content and outcomes restore without another call.
Verify submission, browsing, empty New question, reload, and reopening after
restart in the browser. Use uv for required checks; do not add independent
Chat Session tests.

## Comments

Completed after independent Standards and Spec review on 2026-10-09 UTC.
[Implementation evidence](../validation/ticket-02.md) maps all six criteria to
real SQLite application checks and browser verification.
[Review evidence](../validation/ticket-02-review.md) records both findings and
their fixes. Shared terminal persistence removes a minor duplication; stale
saved-guide responses can no longer restore an old selection after New question
or overwrite a newer saved guide. Both reviewers confirmed resolution.
Browser verification used delayed reads through the actual controls and retained
the same three model calls. The final deterministic suite passed 1,505 tests
with 61 skips; all 29 Node checks passed. No valid finding or unresolved question
remains.
