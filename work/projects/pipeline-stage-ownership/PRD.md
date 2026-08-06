# Pipeline Stage Ownership: Validation, Relevance, and Raw HTML Lifecycle

Labels: completed

## Parent

[Scraping Pipeline PRD](../scraping-pipeline/PRD.md)

## Problem Statement

Validation and relevance classification write into each other's database
columns, so running one stage destroys the other's results. The failure is
reproducible: running `classifier label --review-all` followed by
`validate-articles` erases every human relevance label.

The sequence is a two-step clobber, and each step crosses a stage boundary in
the opposite direction:

1. `--review-all` selects cached articles by relevance provenance alone, with no
   validation filter. Answering `y` writes `validation = 'PENDING'` and `n`
   writes `validation = NULL`. A relevance command re-queued already-`VALIDATED`
   articles for validation.
2. `validate_pending_articles` picks those rows back up and runs post-extraction
   relevance unconditionally, overwriting `relevance_status` and stamping
   `relevance_label_source = 'MODEL'` or `'LLM'` over `'HUMAN'`. A validation
   command destroyed the human labels.

The structural cause is that `update_relevance_status` takes `validation` as a
required positional parameter and always includes it in its `UPDATE`. Every
relevance caller is forced to name a validation value, so the boundary violation
is not an oversight — it is what the function signature demands.

The damage is already present and is not recoverable. Of 79 cached articles only
three retain a `HUMAN` label, and they are exactly the three the overwrite could
not reach: one answered `n` (which set `validation = NULL`, so the validator
never re-selected it), one whose re-validation failed before the relevance block
ran, and one still sitting at `validation = 'PENDING'` awaiting the next run that
would destroy it. Every `HUMAN` label that successfully re-validated is now
indistinguishable from a genuine `LLM` classification. No database backup or log
covering the incident exists.

Three further defects share the same cause:

- `classifier reevaluate` selects `relevance_status IN ('INCONCLUSIVE',
  'IRRELEVANT')` with no `HUMAN` filter at all, and writes `validation` on
  transition. This is a second, independent human-label-loss path, reachable
  without ever running `--review-all`.
- `relevance_status` defaults to `'RELEVANT'` at the schema level. Twenty-two
  articles are currently marked relevant purely by column default, having never
  been assessed by any classifier; seventeen of them had reached the story queue.
- Cache rows whose `raw_html` is `NULL` enter the validation loop, where ground
  truth extraction raises `TypeError` on `None` markup. The exception is
  swallowed by the loop's outer handler, so no status is written and the row
  re-enters the loop on every subsequent run — a silent, permanent retry.

Separately, the pipeline cannot currently train the relevance classifier it is
designed around. The trainer reads embeddings by relevance class from the cache
and finds 39 usable positive examples and **zero** negatives, because every
`IRRELEVANT` row predates post-extraction relevance and carries no embedding.

Resolves inbox items RC-01, RC-05, and RC-02.

## Solution

Give each pipeline stage exclusive ownership of a disjoint set of columns, and
enforce that ownership through function signatures rather than convention. A
stage may freely read another stage's columns; only the owning stage may write
them.

The design rests on one invariant, from which the rest follows:

> `validation = 'VALIDATED'` if and only if a `stories` row exists for that URL.

Validation state answers exactly one question — *do we hold extracted content for
this article?* Extraction and validation are the same operation, and the story
row is where its output lives. An article whose relevance is decided against is
not stored, so its validation state returns to null and the work would be redone
if the decision were ever reversed. Re-extraction is local parsing with no
network cost, so this is a cheap trade for a state model with no ambiguous
middles.

Two independent conditions govern whether work is repeated:

| Question | Condition |
| --- | --- |
| Skip extraction? | A `stories` row already exists |
| Skip relevance? | `relevance_status` is not `'PENDING'` |

Neither substitutes for the other. The first is memoization — a story proves
extraction already ran and produced content. The second is provenance — any
decision, human or automated, means relevance has been settled and must not be
recomputed. A human marking an already-extracted article relevant hits both: no
re-extraction, no reclassification.

Relevance never runs on an article whose extraction has not succeeded, because
before extraction there is nothing to classify beyond page metadata, and the
ingestion process could not consume the result regardless.

Raw HTML becomes disposable. It is deleted the moment its content is durably
stored as a story, and otherwise expires on a uniform thirty-day timer. What
makes this safe is a re-fetch stage that can restore HTML on demand for any
article that needs it, guided by a recorded HTTP status so dead URLs are not
retried indefinitely.

### Stage ownership

| Stage | Owns (exclusive write) | Reads |
| --- | --- | --- |
| Discovery / re-fetch | `raw_html`, `scraped_at`, `fetch_status` | `relevance_status`, `validation`, `stories` |
| Metadata extraction | `headline`, `description`, `embedding` | `raw_html`, `raw_metadata_json` |
| Validation | `validation`, `validation_date`, `stories`, `story_links` | `raw_html`, `relevance_status` |
| Relevance | `relevance_status`, `relevance_label_source` | `headline`, `description`, `embedding`, extracted content |
| Ingestion | `stories.status` transitions | `stories` |

Relevance never writes `validation` — its writer accepts no such parameter. The
one coupled transition is deliberate and lives at the call site, not in the
writer: deciding `IRRELEVANT` or `INCONCLUSIVE` discards content, so the caller
explicitly sets `validation = NULL` and removes any un-ingested story row,
preserving the invariant.

Metadata extraction is separated from relevance so that `headline`,
`description`, and `embedding` are populated whenever HTML is present and they
are missing — including for `HUMAN`-labeled rows where classification is skipped
entirely. Coupling them to the classifier is what currently starves human-labeled
articles of the representation the trainer needs.

## User Stories

1. As a developer, I want `validate-articles` to leave every relevance column
   untouched, so that re-running validation can never destroy a human label.
2. As a developer, I want `classifier reevaluate` to skip `HUMAN`-labeled
   articles, so that retraining the model cannot overwrite my ground truth.
3. As a developer, I want the relevance writer to reject machine updates to
   `HUMAN` rows at the database level, so that a label applied concurrently with
   a running classifier still survives.
4. As a developer, I want an automated relevance write that was rejected to be
   reported back to its caller, so that story creation never acts on a discarded
   classification.
5. As a developer, I want relevance classification to run only when
   `relevance_status` is `'PENDING'`, so that no decision — human or automated —
   is ever recomputed.
6. As a developer, I want validation to skip extraction when a story already
   exists, so that reviewing an article's relevance does not pay for extraction a
   second time.
7. As a developer, I want that skip defeated when selectors have been created
   since the article was validated, so that healed publications re-extract rather
   than serve content from selectors that prompted the heal.
8. As a developer, I want an article marked irrelevant to leave no story row and
   no validation state, so that "we hold content for this article" is never
   claimed falsely.
9. As a developer, I want an article whose relevance is reversed to be
   re-extracted automatically, so that correcting a false negative actually
   reaches the graph.
10. As a developer, I want `relevance_status` to default to `'PENDING'`, so that
    an article is never treated as relevant merely because nothing has assessed
    it.
11. As a developer, I want articles with no cached HTML excluded from the
    validation queue, so that the loop stops failing silently and retrying
    forever.
12. As a developer, I want a re-fetch stage that restores HTML for relevant
    articles that lack it, so that articles can be recovered after purging or
    after a relevance reversal.
13. As a developer, I want the HTTP status of every fetch recorded, so that
    permanently dead URLs are abandoned while transient failures are retried.
14. As a developer, I want re-fetching to write only HTML and fetch state, so
    that restoring content cannot wipe the label that requested it.
15. As a developer, I want re-fetch to run before the validation loop in the same
    invocation, so that recovered articles are validated without a second
    command.
16. As a developer, I want raw HTML deleted as soon as its story is stored, so
    that the database does not retain content it has already extracted.
17. As a developer, I want all other raw HTML to expire on a uniform thirty-day
    timer, so that retention is one rule rather than a per-state matrix.
18. As a developer, I want manual review to select only articles not already
    human-labeled, so that I am never asked to re-answer a question I have
    answered.
19. As a developer, I want marking an article relevant to queue it for
    extraction, so that a human decision produces a story without further
    commands.
20. As a developer, I want the review queue driven by `relevance_status`, so that
    relevance state is not encoded in the validation column.
21. As a data scientist, I want embeddings backfilled for existing irrelevant
    articles, so that the relevance classifier has negative examples and can be
    trained at all.
22. As a data scientist, I want human labels excluded from training input, so
    that they remain an independent evaluation set.
23. As a data scientist, I want the gold-standard example query to return both
    classes without depending on the stories table, so that the LLM classifier
    does not silently degrade to one-sided prompting.

## Implementation Decisions

### Schema

- `scraped_html_cache.relevance_status` default changes from `'RELEVANT'` to
  `'PENDING'`. This default is load-bearing: `'PENDING'` is the discriminator for
  whether relevance has been decided, so an implicit `'RELEVANT'` silently
  defeats it.
- Add `scraped_html_cache.fetch_status` as an integer HTTP status code. A code
  rather than a boolean, so retry policy derives from it directly — 4xx terminal,
  5xx and timeouts retryable — and so a 404 is distinguishable from a 429 when
  inspecting state. Backfill `200` where `raw_html` is present, so `NULL` means
  "never fetched" rather than "fetched before the column existed".
- Remove `'PENDING_RELEVANCE'` from the `validation` CHECK constraint. It is a
  relevance state stored in the validation column and is redundant with
  `relevance_status = 'INCONCLUSIVE'`.
- Retire `'IRRELEVANT'` from the `stories.status` vocabulary. Irrelevant articles
  no longer produce story rows, so the value has no writer.
- Use the existing table-rebuild migration path in `init_db`, which already takes
  a `.backup` copy before rebuilding.

### Database writers

Each column group gets one writer, and no writer accepts a parameter for a column
it does not own.

- A single relevance writer takes URL, status, and label source, and **no
  `validation` parameter**. Removing the parameter is what makes the boundary
  unbreakable: relevance code can no longer express a validation write.
- That writer appends `AND relevance_label_source != 'HUMAN'` to its predicate
  unless the incoming label source is itself `'HUMAN'`. The discriminator falls
  out of the argument already being passed — no new flag, and manual labeling
  keeps working by construction. This guards against a label applied between the
  validator reading a row and writing its classification.
- The writer returns the effective status and source. SQLite's `changes()`
  reports rows matched by the `UPDATE`, so a zero result unambiguously means the
  guard excluded the row. Callers act on the returned value, never on the value
  they attempted to write.
- A metadata writer populates `headline`, `description`, and `embedding`. It is
  idempotent and runs whenever those are missing and HTML or stored metadata is
  available, independent of whether relevance runs.
- A re-fetch writer updates `raw_html`, `scraped_at`, and `fetch_status` only. It
  must not reuse `cache_scraped_html`, which is `INSERT OR REPLACE` with defaults
  of `relevance_status='RELEVANT'` and `relevance_label_source='KEYWORD'` and
  would destroy exactly the label that queued the re-fetch.
- Delete `save_rejected_article` and `get_rejected_article`. Neither is called
  from `src/`; the surviving import in the discovery module is dead, and both
  discovery call sites already cache with `relevance_status='PENDING'`.

### Validation loop

Selection adds `raw_html IS NOT NULL` alongside the existing `PENDING` and
`VALIDATION_FAILED`-retry predicates, which eliminates the silent `TypeError`
retry loop.

Per article:

1. If a story exists for the URL **and** no selector version has been created
   since `validation_date`, set `validation = 'VALIDATED'` and stop. Extraction
   is skipped.
2. Otherwise extract. Failure yields `VALIDATION_FAILED` and failure points as
   today; absent JSON-LD ground truth yields `UNVALIDATABLE`.
3. On success, ensure `headline`, `description`, and `embedding` are populated.
4. If `relevance_status` is `'PENDING'`, run automated relevance — logistic model
   where weights exist, LLM fallback on `INCONCLUSIVE` or absent weights — and
   persist through the guarded writer. Otherwise skip relevance entirely.
5. On the effective decision:
   - `RELEVANT` — write the story with `status = 'UNPROCESSED'` and its links,
     set `validation = 'VALIDATED'`, then delete `raw_html`.
   - `IRRELEVANT` or `INCONCLUSIVE` — write no story, set `validation = NULL`.

Retaining `INCONCLUSIVE` at `validation = NULL` rather than `'VALIDATED'` is
deliberate: it holds no content, so claiming validation would break the
invariant, and a later human decision must be able to queue it for extraction.

### Relevance reversal

Marking an article `IRRELEVANT` sets `validation = NULL` and deletes its story
row **only when that story has not been ingested**. A story at `COMPLETED` has
corresponding Neo4j nodes whose removal is materially more work; those rows are
left in place and the case is deferred. This is the one path where the invariant
is knowingly suspended, and it is bounded to already-ingested articles.

Marking an article `RELEVANT` sets `validation = 'PENDING'`. If a story exists,
the validation loop's skip promotes it to `'VALIDATED'` without re-extracting; if
not, extraction runs and produces one.

### Re-fetch stage

Selects articles that are `RELEVANT`, have no `raw_html`, have no story row, and
whose `fetch_status` is either null or not a terminal 4xx. The story-row
predicate is what prevents re-downloading the entire completed corpus once
immediate purging is in effect.

It runs before the validation loop within the same command invocation, so
recovered articles are validated in one pass, and is additionally exposed as a
standalone command. The crawler logic is extracted from the discovery service and
shared by both callers; the persistence call differs between them.

### Purge

Two rules replace the current per-state matrix:

- `raw_html` is deleted immediately when validation succeeds and a story is
  stored.
- All other `raw_html` expires thirty days after `scraped_at`, regardless of
  validation state.

This supersedes ADR 0003's commitment to retaining failed-article HTML
indefinitely for healing. The trade is accepted because re-fetch makes purging
recoverable: a publication whose selectors drift after its failed articles expire
can restore them on demand, provided the URLs are still live. ADR 0003 is amended
to record the new retention policy.

### Command surfaces

- `classifier label --review-all` selects articles whose label source is not
  `'HUMAN'`. A human answer writes `relevance_status` and
  `relevance_label_source = 'HUMAN'`, and applies the reversal rules above.
- `classifier label` without `--review-all` selects
  `relevance_status = 'INCONCLUSIVE' AND relevance_label_source != 'HUMAN'`,
  replacing the `validation = 'PENDING_RELEVANCE'` selector.
- `classifier reevaluate` selects the same set and writes only relevance columns.
  Restricting it to `INCONCLUSIVE` is deliberate for now; widening it has a
  defined two-step path recorded in the inbox.
- `validate-articles` runs re-fetch, then the validation loop.

### Training data backfill

A one-off script populates `headline` and `description` from `raw_metadata_json`
where present — twelve of the thirteen embedding-less rows retain usable metadata
from the retired `rejected_articles` table — falling back to metadata extraction
from `raw_html` for the remainder, then generates embeddings. This requires no
network access; the data is already in the database in a column the trainer does
not read.

The resulting set is roughly 39 positive to 10 negative examples. That is enough
to fit, thin enough that growing the human-labeled set remains the real
constraint, and skewed enough that the positives — being LLM-derived — will train
an imitator of the LLM rather than of ground truth. The three surviving human
labels are held out as evaluation rather than folded into training.

`get_gold_standard_examples` currently joins `stories` for article text and will
return no negative class once irrelevant articles stop producing stories,
degrading the LLM agent to one-sided few-shot prompting without raising. It is
rewritten to read `headline` and `description` from the cache with no join, which
also fixes an existing asymmetry where human-labeled articles without story rows
were silently excluded.

## Testing Decisions

A good test here asserts externally observable database state after invoking a
public entry point. It does not assert which helper was called or how a statement
was composed. Existing tests in `tests/test_article_validator.py` establish the
pattern: seed a temporary SQLite database, patch only the external adapters — the
classifier weight loader, the embedding adapter, and the LLM classification
agent — and assert on rows afterward.

Three seams, two of which already exist.

**Primary — the validator entry point.** Running against a temporary database
with only external adapters patched, this covers the majority of the spec: the
`HUMAN` guard, relevance conditionality, the story-exists skip and its defeat by
newer selectors, the invariant across every branch, and the `validation = NULL`
transitions. The re-fetch stage is invoked from inside this entry point
specifically so it is exercised at the same seam, needing only the crawler
patched.

**Secondary — the relevance writer.** Required as its own seam only for the
concurrent case, where a `HUMAN` label must be applied between read and write.
Because the manual labeling command delegates to this same writer, human labeling
needs no separate seam and the CLI's input loop stays untested.

**Tertiary — the purge function.** Retention policy in isolation.

Specific assertions:

- The reported regression end to end: seed a validated article, apply a `HUMAN`
  label, run validation, assert the label and its source are unchanged.
- The second loss path: seed a `HUMAN`-labeled article, run reevaluate with
  weights that would reclassify it, assert the label is untouched.
- A machine write against a `HUMAN` row reports rejection to its caller, and the
  caller creates no story from the discarded classification.
- Relevance is not invoked at all — not the weight loader, the embedding adapter,
  or the LLM agent — for a row whose `relevance_status` is not `'PENDING'`.
- Extraction is skipped when a story exists, and performed when a selector
  version postdates `validation_date`.
- The invariant holds after every branch: relevant articles end `'VALIDATED'`
  with a story; irrelevant and inconclusive articles end at null validation with
  no story.
- A row with null `raw_html` is not selected by the validation loop.
- Re-fetch preserves `relevance_status`, `relevance_label_source`, `headline`,
  `description`, and `embedding` across a restore.
- Re-fetch does not select articles that already have a story row, and abandons
  URLs whose recorded status is a terminal 4xx.
- Raw HTML is absent immediately after a story is written, and present for an
  article that failed validation within the retention window.
- Reversing a relevance decision on an un-ingested article removes its story;
  reversing it on an ingested article does not.
- `get_gold_standard_examples` returns both classes with no story rows present.
- The backfill produces embeddings for both classes, verified by the trainer's
  own selection query returning a non-zero count per class.

Test files referencing the deleted rejected-article helpers require updating:
`tests/test_db.py`, `tests/test_incremental_discovery.py`,
`tests/test_relevance_filter.py`, `tests/test_relevance_classifier.py`, and
`tests/test_archive_crawl.py`, which uses the getter for assertions and needs a
direct cache query instead.

## Out of Scope

- Moving relevance classification ahead of validation. This is the intended
  destination, not a divergence — the classifier is simply not trained yet, and
  the current post-extraction placement exists because the LLM classifies far
  better with article body text than with page metadata alone. The move happens
  once the classifier is trained and evaluated.
- Widening `reevaluate` beyond `INCONCLUSIVE`.
- Removing Neo4j nodes for articles whose relevance is reversed after ingestion.
- Recovering the human labels already lost. No backup or log covering the
  incident exists.
- Training or evaluating the relevance classifier. This spec produces its
  dataset; using it is separate work.
- Making the validator synchronous.

## Further Notes

The `HUMAN` guard should land first and on its own. One cache row is currently
`relevance_status = 'RELEVANT'`, `relevance_label_source = 'HUMAN'`, and
`validation = 'PENDING'` — the next `validate-articles` run destroys it under
present behavior. That row is one of only three surviving human labels.

Take a database backup before the schema migration. Human labels are now
expensive to produce and there is no other copy.

Ordering thereafter: schema and writers, then the validation loop, then the
command surfaces, then re-fetch and purge, then the backfill. The backfill is
last because it depends on the metadata writer but nothing depends on it.

Two observations worth carrying forward. Validation's per-article cost is local
CPU, but its *failure accounting* is not: failure points accrue at up to three
per failing article and trip a circuit breaker at ten, which spawns a
generator/critic healing loop — the most expensive operation in the pipeline.
That accounting is currently blind to relevance, so roughly four irrelevant
articles that fail extraction can trigger a full healing cycle for content
outside the subject matter. This is the strongest argument for eventually moving
the classifier ahead of validation, and it is stronger than the compute argument.
Usefully, metadata extraction reads JSON-LD and meta tags rather than publication
selectors, so it still works on pages where selector extraction fails — which is
exactly what a pre-validation gate would need.

Second: the twenty-two default-relevant articles are a live instance of the
schema-default defect, not a hypothetical. Seventeen had reached the story queue
without assessment and have since been removed from `stories`; their cache rows
remain and will be reclassified once `relevance_status` defaults correctly and
they are marked `'PENDING'`.
