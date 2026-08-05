# Apply reversal semantics to manual review

Labels: completed

## Parent

[Pipeline Stage Ownership: Validation, Relevance, and Raw HTML Lifecycle](../PRD.md)

## What to build

A human decision produces the right downstream state without further commands,
and reviewing stops asking questions that have already been answered.

`classifier label --review-all` selects articles whose label source is not
`'HUMAN'`. It currently selects on relevance provenance with no validation filter
and then writes the validation column on the way out, which is what re-queued
already-validated articles and set up the label loss. It now writes relevance
columns only, and applies the coupled transition explicitly at the call site.

Marking an article relevant sets validation to `'PENDING'`. If a Story already
exists the loop's skip promotes it to `'VALIDATED'` without re-extracting; if not,
extraction runs and produces one. Either way, correcting a false negative
actually reaches the graph.

Marking an article irrelevant clears its validation state and removes its Story
row, so the pipeline never claims to hold content it has discarded — but only
when that Story has not been ingested. A completed Story has corresponding Neo4j
nodes whose removal is materially more work. Those rows are left in place and the
case is deferred; this is the one path where the invariant is knowingly
suspended, and it is bounded to already-ingested articles.

## Acceptance criteria

- [x] `--review-all` presents only articles whose label source is not `'HUMAN'`.
- [x] A human answer records `relevance_status` and `relevance_label_source = 'HUMAN'`, and writes nothing else through the relevance writer.
- [x] Marking an article relevant leaves it at `validation = 'PENDING'`, and a subsequent validation run produces a Story for it.
- [x] Marking an article relevant when a Story already exists promotes it to `'VALIDATED'` without re-extraction.
- [x] Marking an un-ingested article irrelevant removes its Story row and clears its validation state.
- [x] Marking an already-ingested article irrelevant records the label and leaves the Story row in place.
- [x] No manual review path writes the validation column through the relevance writer.
- [x] The full deterministic test suite passes.

## Blocked by

- 04 — Give relevance and validation disjoint writers.
- 05 — Enforce the story invariant in the validation loop.
