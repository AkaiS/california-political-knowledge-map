# Backfill training data and fix the gold-standard query

Labels: completed

## Parent

[Pipeline Stage Ownership: Validation, Relevance, and Raw HTML Lifecycle](../PRD.md)

## What to build

The relevance classifier the pipeline is designed around cannot currently be
trained. The trainer reads embeddings by relevance class from the cache and finds
thirty-nine usable positives and **zero** negatives, because every irrelevant
article predates post-extraction relevance and carries no embedding.

A one-off backfill fixes this without any network access. Twelve of the thirteen
embedding-less articles retain usable headline and description in the cache's
stored metadata column — data already in the database, in a column the trainer
does not read. Populate headline and description from there, fall back to
extracting them from raw HTML for the remainder, then generate embeddings through
the metadata writer.

The resulting set is roughly thirty-nine positive to ten negative. That is enough
to fit, thin enough that growing the human-labeled set remains the real
constraint, and skewed enough that the positives — being LLM-derived — will train
an imitator of the LLM rather than of ground truth. The three surviving human
labels are held out as an independent evaluation set rather than folded into
training.

Separately, the gold-standard example query joins the Story table for article
text. Once irrelevant articles stop producing Stories it returns no negative
class at all, silently degrading the LLM classifier to one-sided few-shot
prompting without raising. It is rewritten to read headline and description from
the cache with no join, which also fixes an existing asymmetry where
human-labeled articles without Story rows were excluded.

## Acceptance criteria

- [x] Every irrelevant and inconclusive article that had usable stored metadata has a headline, a description, and an embedding after the backfill.
- [x] Articles without stored metadata but with raw HTML have theirs extracted from the HTML.
- [x] The backfill requires no network calls.
- [x] The trainer's own selection query returns a non-zero count for both the relevant and the irrelevant class.
- [x] Human-labeled articles are excluded from training input and remain available as an evaluation set.
- [x] The gold-standard example query returns both classes with no Story rows present in the database.
- [x] The gold-standard example query includes human-labeled articles that have no Story row.
- [x] The backfill is idempotent: a second run changes nothing.
- [x] The full deterministic test suite passes.

## Blocked by

- 04 — Give relevance and validation disjoint writers.
- 05 — Enforce the story invariant in the validation loop.
