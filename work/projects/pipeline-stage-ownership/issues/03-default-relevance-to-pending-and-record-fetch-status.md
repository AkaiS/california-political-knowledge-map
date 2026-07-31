# Default relevance to PENDING and record fetch status

Labels: ready-for-agent

## Parent

[Pipeline Stage Ownership: Validation, Relevance, and Raw HTML Lifecycle](../PRD.md)

## What to build

An article is never treated as relevant merely because nothing has assessed it.
The cache currently defaults `relevance_status` to `'RELEVANT'`, which silently
defeats the discriminator the whole design rests on — `'PENDING'` is how the
pipeline knows relevance has not been decided. Twenty-two articles are marked
relevant today purely by that default, having never been seen by any classifier;
seventeen of them had reached the Story queue.

The default becomes `'PENDING'`, and those twenty-two rows are reset so they will
be classified on the next run.

The cache also gains a recorded HTTP status for each fetch, stored as an integer
code rather than a boolean so retry policy derives from it directly — 4xx
terminal, 5xx and timeouts retryable — and so a 404 is distinguishable from a 429
when inspecting state. Existing rows holding HTML are backfilled to `200`, so a
null means "never fetched" rather than "fetched before the column existed".

Finally, `'PENDING_RELEVANCE'` leaves the validation vocabulary. It is a relevance
state stored in the validation column and is redundant with an `'INCONCLUSIVE'`
relevance status. The one command that selects on it — `classifier label` without
`--review-all` — selects on `relevance_status` instead, so the review queue is
driven by relevance state rather than by the validation column.

Take a database backup before migrating. Human labels are now expensive to
produce and there is no other copy.

## Acceptance criteria

- [ ] A newly cached article whose relevance nothing has assessed has `relevance_status = 'PENDING'`.
- [ ] The twenty-two articles marked relevant by the old default are `'PENDING'` after migration.
- [ ] Articles carrying a real classification — from a keyword match, a model, an LLM, or a human — keep their status and source across the migration.
- [ ] Every cache row holding raw HTML has a recorded fetch status of `200`; rows that were never fetched have none.
- [ ] `'PENDING_RELEVANCE'` is rejected by the validation constraint.
- [ ] `classifier label` without `--review-all` presents articles selected by `relevance_status = 'INCONCLUSIVE'` and a non-human label source, and no longer reads the validation column.
- [ ] The migration runs through the existing table-rebuild path, which takes its own copy before rebuilding.
- [ ] The full deterministic test suite passes.

## Blocked by

None - can start immediately.
