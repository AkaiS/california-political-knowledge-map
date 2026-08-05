# Backfill training data and fix the gold-standard query

Labels: ready-for-agent

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
- [ ] ~~Human-labeled articles are excluded from training input and remain available as an evaluation set.~~ Withdrawn; see the 2026-08-04 comment. Superseded by the Evaluation Split access rules in [Build the initial Relevance Filter Evaluation Gold Set](../../../initiatives/model-evaluation/issues/03-build-initial-relevance-evaluation-gold-set.md).
- [x] The gold-standard example query returns both classes with no Story rows present in the database.
- [x] The gold-standard example query includes human-labeled articles that have no Story row.
- [x] The backfill is idempotent: a second run changes nothing.
- [x] The full deterministic test suite passes.

## Blocked by

- 04 — Give relevance and validation disjoint writers.
- 05 — Enforce the story invariant in the validation loop.
- [Build the initial Relevance Filter Evaluation Gold Set](../../../initiatives/model-evaluation/issues/03-build-initial-relevance-evaluation-gold-set.md)
  — for the remaining trainer criterion only.

## Comments

### 2026-08-04 — Trainer criterion reopened; the holdout mechanism was the wrong one

Found during a review of this branch. Two of the criteria above were checked but
the trainer cannot in fact be fitted, and the two are the reason why: as written
they cannot both hold.

`get_training_rows` filters to `relevance_label_source = 'LLM'`, satisfying
"human-labeled articles are excluded from training input". The actual contents of
`document_store.db`:

| Relevance Status | Label source | Rows | With embeddings |
| --- | --- | --- | --- |
| `RELEVANT` | `HUMAN` | 79 | 44 |
| `IRRELEVANT` | `HUMAN` | 13 | 3 |
| `RELEVANT` | `LLM` | 1 | 1 |

Every irrelevant article is human-labeled. Excluding human labels therefore
removes the whole negative class, and the query matches one row of one class. No
backfill fixes this: the backfill adds headlines, descriptions, and embeddings,
never a label source.

The premise that made these compatible was this issue's own statement that "the
three surviving human labels are held out as an independent evaluation set" —
true when written, when three human labels existed and label source was the only
holdout available. There are now 92, and the evaluation subsystem exists.
`EvaluationSplit` (`src/knowledge_map/evaluation/definitions.py:352`) carries
`training` / `calibration` / `held-out`, and `revise_evaluation_gold_set`
guarantees no revision walks a case out of `held-out`, so leakage is prevented
structurally rather than by a `WHERE` clause the trainer has to get right.

Gold Set issue 03 already decides the policy this issue was approximating: the
`training` split is for "Logistic-regression fitting only. May contain human
labels; never contains held-out groups." So human labels belong in training, and
the exclusion should key on gold-set membership and split, not on
`relevance_label_source`. The second criterion is withdrawn rather than reopened
because it asks for the wrong thing.

The same correction applies to `get_gold_standard_examples`, which draws the
Relevance Agent's few-shot examples from human-labeled rows with no split
awareness and can therefore pull a held-out case into a prompt. That is covered
by issue 03's final acceptance criterion and is recorded there.

Nothing was changed in the trainer. A prerequisite is unresolved: no relevance
Evaluation Task Contract exists yet, and nothing maps an Evaluation Case back to
an article URL, so "exclude anything in a gold case" has no join key today.
Establishing it is part of the Gold Set work, not of this issue.
