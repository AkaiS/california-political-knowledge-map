# 04 Update a guide or edit its question

Labels: enhancement, completed
Parent: [Source Guides spec](../PRD.md)

## What to build

Provide explicit Update guide for the saved question and Edit question for a
new investigation. Updates retain the guide's identity; submitting an edited
complete question creates a separate guide. Keep previous reading available
while an update runs or fails.

## Acceptance criteria

- [x] Update guide starts a new attempt for the same saved question and stable
  guide identity. The current content remains readable while it runs.
- [x] A successful update atomically replaces content and retrieval information,
  including a successful empty outcome that replaces previous articles.
- [x] A failed update records the latest failure but preserves previous content
  and its last successful retrieval date. The UI distinguishes latest attempt
  timing/status from saved content's retrieval/update information.
- [x] Edit question restores the complete question in editable input. Submission
  saves a new independent guide and uses its explicit wording without rewriting
  or approval. The original guide remains available; no lineage view is required.
- [x] Conflicting updates on one guide are serialized rather than allowing
  an older attempt to overwrite newer content. Each attempt has a distinct
  execution identity and only the active attempt can publish.
- [x] Opening, reload, ingestion, and navigation trigger no implicit updates.

## Blocked by

- [03 Keep independent searches running across navigation](03-continue-independent-searches.md)

## Validation

Exercise update and edit through application operations with temporary real
SQLite and event-controlled retrieval/model substitutes. Check stable versus
new identities, running retention, successful empty replacement, failed-update
timestamps, and conflicting completion through externally visible results.
Verify Edit question and Update guide controls and retained reading in the
browser. Run required checks with uv; do not add a separate Chat Session seam.

## Comments

Completed after independent Standards and Spec review on 2026-10-09 UTC.
[Implementation validation](../validation/ticket-04.md) maps all six acceptance
criteria to controlled application and browser evidence.
[Review evidence](../validation/ticket-04-review.md) records both reports,
the shared admission-check correction, and final verification. No valid
ticket 04 finding remains unresolved.
