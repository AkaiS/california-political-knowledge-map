  Pipeline Stage Ownership: Validation, Relevance, and Story Migration

Labels: proposed

## Parent

[Scraping Pipeline PRD](../scraping-pipeline/PRD.md)

## Problem Statement

Validation and relevance classification write into each other's database
columns, so running one stage destroys the other's results. The failure is
reproducible: running `classifier label --review-all` followed by `validate`
erases every human relevance label.

The sequence is a two-step clobber, and each step crosses a stage boundary in
the opposite direction:

1. `--review-all` selects cached articles by relevance provenance alone, with no
   validation filter ([main.py:859](../../../src/knowledge_map/cli/main.py:859)).
   Answering `y` writes `validation = 'PENDING'` and `n` writes
   `validation = NULL` ([main.py:896](../../../src/knowledge_map/cli/main.py:896)).
   A relevance command re-queued already-`VALIDATED` articles for validation.
2. `validate_pending_articles` picks those rows back up and runs post-validation
   relevance unconditionally, overwriting `relevance_status` and stamping
   `relevance_label_source = 'MODEL'` or `'LLM'` over `'HUMAN'`
   ([validation.py:652-673](../../../src/knowledge_map/core/validation.py:652)).
   A validation command destroyed the human labels.

The structural cause is that `update_relevance_status` takes `validation` as a
**required positional parameter** and always includes it in its `UPDATE`
([sqlite_db.py:858](../../../src/knowledge_map/adapters/sqlite_db.py:858)). Every
relevance caller is forced to name a validation value, so the boundary violation
is not an oversight — it is what the function signature demands.

Three further defects share the same cause:

- `classifier reevaluate` selects `relevance_status IN ('INCONCLUSIVE',
  'IRRELEVANT')` with **no `HUMAN` filter at all**
  ([main.py:943](../../../src/knowledge_map/cli/main.py:943)) and writes
  `validation` on transition
  ([main.py:968](../../../src/knowledge_map/cli/main.py:968)). This is a second,
  independent human-label-loss path, reachable without ever running
  `--review-all`.
- The `IRRELEVANT` branch of post-validation relevance passes `validation=None`
  ([validation.py:664](../../../src/knowledge_map/core/validation.py:664)),
  erasing the `VALIDATED` status written 60 lines earlier. A successfully
  validated but irrelevant article ends with `validation = NULL`.
- `validation = 'VALIDATED'` is committed before the story content is saved, and
  an **async LLM classification call** sits between the two
  ([validation.py:634-650](../../../src/knowledge_map/core/validation.py:634)).
  Any exception there is swallowed by the outer handler
  ([validation.py:743](../../../src/knowledge_map/core/validation.py:743)),
  leaving `VALIDATED` with no story row.

Relevance is also being assigned to articles whose extraction never succeeded.
Those articles have none of the information the ingestion process requires, so
the classification is both premature and unusable.

Resolves inbox items RC-01, RC-05, and RC-02.

## Solution

Give each pipeline stage exclusive ownership of a disjoint set of columns, and
enforce that ownership through function signatures rather than convention. A
stage may freely *read* another stage's columns; only the owning stage may
*write* them.

Relevance classification is gated on successful validation. Story creation is
removed from both validation and relevance and becomes its own migration stage,
which can run automatically after a relevance pass or be invoked on its own.

### Stage ownership

| Stage | Owns (exclusive write) | Reads |
| --- | --- | --- |
| Discovery | `url`, `publication_id`, `raw_html`, `scraped_at`; initial `validation = 'PENDING'`, `relevance_status = 'PENDING'` | — |
| Validation | `validation`, `validation_date`, `extracted_*` fields | `raw_html` |
| Relevance | `relevance_status`, `relevance_label_source`, `headline`, `description`, `embedding` | `validation`, `extracted_*` |
| Migration | `stories.*`, `story_links.*` | `validation`, `relevance_status`, `extracted_*` |
| Ingestion | `stories.status` transitions | `stories.*` |

Validation never reads or writes relevance columns. Relevance never writes
`validation` or `validation_date`. Neither writes `stories`.

### Stage sequence

1. **Discovery** caches the row with `validation = 'PENDING'` and
   `relevance_status = 'PENDING'`. Unchanged.
2. **Validation** processes `validation = 'PENDING'` rows plus the existing
   `VALIDATION_FAILED` retry window. On success it persists the extracted fields
   onto the cache row, then sets `validation = 'VALIDATED'`. It persists nothing
   else.
3. **Relevance** processes `validation = 'VALIDATED' AND relevance_status =
   'PENDING' AND relevance_label_source != 'HUMAN'`. Nothing outside that set is
   eligible.
4. **Migration** copies `validation = 'VALIDATED' AND relevance_status =
   'RELEVANT'` cache rows into `stories` with `status = 'UNPROCESSED'`, plus
   their `story_links`.
5. **Ingestion** consumes `stories.status = 'UNPROCESSED'`. Unchanged.

### Why the cache row must carry the extracted fields

Removing story writing from validation leaves the extracted title, author,
published date, body, and links with nowhere to live between stages 2 and 4.
Re-extracting from `raw_html` at migration time is not viable: it duplicates the
whole of validation's work, and `purge_html_cache` nulls `raw_html` once a story
reaches `COMPLETED`
([sqlite_db.py:1191](../../../src/knowledge_map/adapters/sqlite_db.py:1191)).

The cache row therefore becomes the staging record and `stories` becomes a pure
ingestion queue derived from it. This is the same ownership statement as
"validation owns extracted content and metadata," made physical.

## User Stories

1. As a developer, I want to run `classifier label --review-all` without
   changing any article's validation state, so that reviewing labels never
   re-queues validated work.
2. As a developer, I want `validate` to leave every relevance column untouched,
   so that re-running validation can never destroy a human label.
3. As a developer, I want `classifier reevaluate` to skip `HUMAN`-labeled
   articles, so that retraining the model cannot overwrite my ground truth.
4. As a developer, I want relevance classification to run only on successfully
   validated articles, so that I never label articles whose content the
   ingestion process does not have.
5. As a developer, I want `validation = 'VALIDATED'` to be written only after
   the extracted content is durably stored, so that an interruption can never
   leave a validated row without its content.
6. As a developer, I want story creation to be a separate migration step I can
   invoke on its own, so that I can re-run it after labeling without re-running
   validation.

## Implementation Decisions

### Schema

- Add to `scraped_html_cache`: `extracted_title`, `extracted_author`,
  `extracted_published_date`, `extracted_content`, `extracted_links_json`. The
  `extracted_` prefix keeps these distinct from the relevance-owned `headline`
  and `description`, which are page metadata rather than extraction output.
- Use the existing table-rebuild migration path in `init_db`
  ([sqlite_db.py:60-145](../../../src/knowledge_map/adapters/sqlite_db.py:60)),
  which already takes a `.backup` copy before rebuilding.
- Leave `'PENDING_RELEVANCE'` in the `validation` CHECK constraint. Nothing will
  write it after this change; removing the enum value is a separate rebuild and
  is deferred to the inbox.

### Database writers

Each column group gets exactly one writer, and no writer accepts a parameter for
a column it does not own.

- `update_cached_html_status(url, validation)` — unchanged. The **only** writer
  of `validation` and `validation_date`.
- `update_cached_html_extraction(url, title, author, published_date, content, links)`
  — new. Validation-owned writer for the `extracted_*` fields.
- `update_cached_html_relevance(url, relevance_status, label_source)` — new.
  Writes those two columns and nothing else. Used by the review commands
  (`--review-all`, `reevaluate`), which operate on articles whose metadata
  already exists.
- `update_relevance_status(url, status, label_source, headline, description, embedding)`
  — **drop the `validation` parameter entirely.** Retained for the automated
  classifier, which is the only caller that computes and persists the
  headline/description/embedding representation. Removing the parameter is what
  makes the boundary unbreakable: relevance code can no longer express a
  validation write.
- `migrate_relevant_stories(db_path) -> int` — new. Selects `validation =
  'VALIDATED' AND relevance_status = 'RELEVANT'`, inserts into `stories` with
  `status = 'UNPROCESSED'` and the row's `extracted_*` values, and writes
  `story_links`. Idempotent via the existing `INSERT OR IGNORE` on the unique
  `url` ([sqlite_db.py:229](../../../src/knowledge_map/adapters/sqlite_db.py:229)).
  Returns the number of stories created.
- Delete `save_rejected_article` and `get_rejected_article`. Neither is called
  from `src/`; the `save_rejected_article` import in
  [discovery.py:11](../../../src/knowledge_map/core/discovery.py:11) is dead and
  both discovery call sites already use
  `cache_scraped_html(..., relevance_status="PENDING")`.

### Validation

`validate_pending_articles` persists validation state and extracted fields only.
Remove the relevance block
([validation.py:620-673](../../../src/knowledge_map/core/validation.py:620)) and
the `save_story` call
([validation.py:675-684](../../../src/knowledge_map/core/validation.py:675))
outright.

Per-article write order on success becomes:

1. `widen_selector_version_window(...)`
2. `update_cached_html_extraction(...)`
3. `update_cached_html_status(url, 'VALIDATED')`

Writing `VALIDATED` last gives the required invariant without a cross-connection
transaction. Every adapter helper opens and commits its own `sqlite3.connect`,
so a shared transaction would be an adapter-layer refactor; with this ordering an
interruption instead leaves `validation = 'PENDING'` with extracted fields
already written, and the next run simply redoes the article.

With relevance removed, the function no longer awaits anything. Keep it `async`
for now to avoid touching the three CLI call sites
([main.py:566](../../../src/knowledge_map/cli/main.py:566),
[596](../../../src/knowledge_map/cli/main.py:596),
[610](../../../src/knowledge_map/cli/main.py:610)); note the cleanup in the
inbox.

### Relevance

Move the classification logic out of `validation.py` into
`relevance_classification.py` as `classify_validated_articles(db_path)`,
selecting:

```sql
WHERE validation = 'VALIDATED'
  AND relevance_status = 'PENDING'
  AND relevance_label_source != 'HUMAN'
```

Behavior within a row is unchanged: metadata embedding, logistic model when
weights exist, LLM fallback on `INCONCLUSIVE` or absent weights. It reads
`extracted_title` and `extracted_content` from the cache row rather than from
in-memory extraction output. It calls `update_relevance_status` and writes no
validation column, so the `validation=None` erasure on the `IRRELEVANT` path
disappears by construction.

`stories.status = 'IRRELEVANT'`
([validation.py:681](../../../src/knowledge_map/core/validation.py:681)) is
retired. Irrelevant articles simply never migrate. `stories.status` returns to
its single purpose of tracking ingestion progress, and the training dataset is
read from the cache instead.

### CLI

- `classifier label` without `--review-all`: replace the
  `validation = 'PENDING_RELEVANCE'` selector
  ([main.py:865](../../../src/knowledge_map/cli/main.py:865)) with
  `relevance_status = 'INCONCLUSIVE' AND relevance_label_source != 'HUMAN'`.
  This removes the last dependence on a relevance state stored in the validation
  column.
- `classifier label` with `--review-all`: add `AND validation = 'VALIDATED'` to
  the selector. A human answer calls `update_cached_html_relevance` and changes
  only `relevance_status` and `relevance_label_source = 'HUMAN'`. Drop the
  `validation = "PENDING"` / `None` assignment
  ([main.py:896](../../../src/knowledge_map/cli/main.py:896)) and the
  `get_metadata_embedding` backfill — a validated row always has its embedding
  from the classify stage.
- `classifier reevaluate`: narrow the selector to
  `relevance_status = 'INCONCLUSIVE' AND relevance_label_source != 'HUMAN' AND
  validation = 'VALIDATED'`. Restricting to `INCONCLUSIVE` for now is
  deliberate; widening it is an inbox item with a defined two-step path.
  Transitions call `update_cached_html_relevance` and write no validation
  column.
- Add `ca-map migrate-stories` invoking `migrate_relevant_stories`, reporting
  the count created.
- The `validate` command runs validation, then `classify_validated_articles`,
  then `migrate_relevant_stories`, preserving today's end-to-end behavior from a
  single command.
- Run migration at the end of `--review-all` and `reevaluate` as well, so a
  label change promoting an article to `RELEVANT` reaches `stories` without a
  second command.

### Ingestion eligibility

Unchanged and unqualified: `stories.status = 'UNPROCESSED'` with non-empty
content ([sqlite_db.py:310](../../../src/knowledge_map/adapters/sqlite_db.py:310)).
Validation and relevance are enforced by the migration gate, so ingestion does
not need to re-check them.

### Gold standard examples

`get_gold_standard_examples`
([sqlite_db.py:824](../../../src/knowledge_map/adapters/sqlite_db.py:824)) joins
`scraped_html_cache` to `stories` for article content. Once irrelevant articles
no longer receive story rows, the `IRRELEVANT` half of the balanced set silently
returns empty and the LLM agent degrades to a one-sided few-shot prompt without
raising. Rewrite it to read `extracted_title` and `extracted_content` from the
cache and drop the join.

## Testing Decisions

- **Regression, the reported failure:** seed a `VALIDATED` article, apply a
  `HUMAN` label via `--review-all`, run `validate_pending_articles`, and assert
  `relevance_status` and `relevance_label_source = 'HUMAN'` are unchanged and
  `validation` is still `'VALIDATED'`.
- **Regression, the second path:** seed a `HUMAN`-labeled `IRRELEVANT` article,
  run `reevaluate` with weights that would classify it `RELEVANT`, and assert
  the label is untouched.
- Assert `update_relevance_status` and `update_cached_html_relevance` cannot
  write `validation` — inspect the generated SQL or assert the column is
  unchanged across a call.
- Assert `classify_validated_articles` skips rows with `validation` in
  `PENDING`, `VALIDATION_FAILED`, `UNVALIDATABLE`.
- Assert a successfully validated but `IRRELEVANT` article retains
  `validation = 'VALIDATED'` and receives no story row.
- Assert write ordering: with `update_cached_html_status` patched to raise, the
  extracted fields are present and `validation` is still `'PENDING'`.
- Assert `migrate_relevant_stories` is idempotent — two runs produce one story
  row and one set of `story_links`.
- Assert `get_gold_standard_examples` still returns both classes when no
  irrelevant article has a story row.
- Update the four test files referencing the removed functions:
  `tests/test_db.py`, `tests/test_incremental_discovery.py`,
  `tests/test_relevance_filter.py`, `tests/test_relevance_classifier.py`.
  `tests/test_archive_crawl.py` uses `get_rejected_article` for assertions and
  needs a direct cache query instead.

## Sequencing

1. Schema migration and the new/narrowed database writers, with their tests.
   Nothing behavioral changes yet.
2. Strip relevance and story writing from `validate_pending_articles`; reorder
   the `VALIDATED` write. Pipeline is temporarily incomplete.
3. Add `classify_validated_articles` and `migrate_relevant_stories`; wire the
   `validate` command to the three-stage sequence. Pipeline is whole again.
4. Narrow the review commands and add `migrate-stories`.
5. Delete `save_rejected_article`/`get_rejected_article`, fix
   `get_gold_standard_examples`, update tests.

Steps 2 and 3 must land together; between them no story rows are produced.

## Deferred to inbox

- Re-fetch raw HTML for cache rows whose HTML was purged but which need
  re-evaluation.
- Widen `reevaluate` coverage. Step one: include `IRRELEVANT` alongside
  `INCONCLUSIVE`, both guaranteed never ingested, still excluding `HUMAN`. Step
  two: include `RELEVANT`, which requires removing already-ingested nodes from
  the Neo4j graph — substantially more work.
- Remove `'PENDING_RELEVANCE'` from the `validation` CHECK constraint once no
  rows carry it.
- Clean up existing `stories` rows with `status = 'IRRELEVANT'`.
- Make `validate_pending_articles` synchronous now that it awaits nothing.
