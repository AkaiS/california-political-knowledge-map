# Skip extraction when a Story already exists

Labels: completed

## Parent

[Pipeline Stage Ownership: Validation, Relevance, and Raw HTML Lifecycle](../PRD.md)

## What to build

Reviewing an article's relevance stops paying for extraction a second time. A
Story row is proof that extraction already ran and produced content, so when one
exists the validation loop marks the article `'VALIDATED'` and moves on without
re-parsing.

This is memoization, not a relevance check. It composes with the relevance skip
from ticket 05 rather than substituting for it: a human marking an
already-extracted article relevant hits both conditions and neither re-extracts
nor reclassifies.

The skip is defeated when a Selector Version has been created for the publication
since the article was validated. Content extracted with selectors that predate a
heal is exactly the content the heal was meant to replace, so a healed
publication re-extracts rather than serving it.

## Acceptance criteria

- [x] An article with an existing Story row is marked `'VALIDATED'` without extraction being performed.
- [x] An article with an existing Story row whose publication has a Selector Version created after the article's validation date is re-extracted.
- [x] Re-extraction after a heal replaces the Story's content rather than silently leaving the prior content in place.
- [x] The skip does not bypass the relevance condition: an article with an existing Story and `'PENDING'` relevance is still classified.
- [x] The invariant still holds on both paths.
- [x] The full deterministic test suite passes.

## Blocked by

- 05 — Enforce the story invariant in the validation loop.
