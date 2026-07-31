# Replace per-state retention with a uniform thirty-day timer

Labels: ready-for-agent

## Parent

[Pipeline Stage Ownership: Validation, Relevance, and Raw HTML Lifecycle](../PRD.md)

## What to build

Raw HTML retention becomes two rules instead of a per-state matrix that is hard
to reason about and harder to verify:

- Raw HTML is deleted immediately when validation succeeds and a Story holds its
  extracted content.
- All other raw HTML expires thirty days after it was scraped, regardless of
  validation state.

Purging removes the raw HTML, not the cache record. Provenance, relevance, and
fetch state all survive.

This supersedes the earlier commitment to retaining failed-article HTML
indefinitely so that Selector Healing always has material. The trade is accepted
because re-fetch makes purging recoverable: a publication whose selectors drift
after its failed articles expire can restore them on demand, provided the URLs
are still reachable. That is why this ticket is sequenced after re-fetch rather
than before it. ADR 0003 already records the amended policy.

## Acceptance criteria

- [ ] Raw HTML is absent immediately after a Story is written for an article, without waiting for a purge run.
- [ ] Raw HTML for an article that failed validation within the last thirty days is still present after a purge run.
- [ ] Raw HTML older than thirty days is removed regardless of validation state, including `VALIDATION_FAILED`, `UNVALIDATABLE`, and null.
- [ ] Purging removes only the raw HTML; the cache record and its relevance, provenance, and fetch columns remain.
- [ ] No retention rule keyed to a specific validation state remains in the purge path.
- [ ] The full deterministic test suite passes.

## Blocked by

- 05 — Enforce the story invariant in the validation loop.
- 08 — Restore HTML for relevant articles that lack it.
