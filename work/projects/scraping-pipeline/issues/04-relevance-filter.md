# 04. Relevance Filter & `rejected_articles`

Labels: completed

## Parent

[Scraping Pipeline PRD](../PRD.md)

## What to build

Create the `rejected_articles` SQLite table (statuses `IRRELEVANT` and `INCONCLUSIVE`, with metadata JSON for later false-negative analysis) and implement the metadata phase of the Relevance Filter, wired into the `update-sources` fetch path from issue 03.

After a candidate page is fetched, extract its JSON-LD `headline`/`description` (falling back to HTML meta tags) and classify per the PRD's Classification Logic against the global `POLITICAL_RELEVANCE_KEYWORDS` list: `RELEVANT` articles keep their cached raw HTML as `PENDING` (no duplicate fetch); `IRRELEVANT` articles (negative-topic match or zero political matches) are recorded in `rejected_articles` and their HTML discarded; `INCONCLUSIVE` articles (secondary local/state terms, no negatives) are recorded as `INCONCLUSIVE` with a clear code seam for the future embeddings-based classifier.

## Acceptance criteria

- [x] `rejected_articles` table is created on database initialization with the PRD schema
- [x] Fetched candidates are classified `RELEVANT` / `IRRELEVANT` / `INCONCLUSIVE` from JSON-LD or meta-tag metadata against the keyword configuration
- [x] `RELEVANT` articles remain cached as `PENDING` without a second network request; rejected articles are recorded with their Relevance Status and metadata
- [x] Previously rejected URLs are skipped on subsequent `update-sources` runs (verifies the issue 03 skip-check end-to-end)
- [x] A documented hook exists for passing `INCONCLUSIVE` metadata to a future logistic regression classifier
- [x] Tests cover keyword matching, negative-topic rejection, inconclusive classification, meta-tag fallback, and rejected-article persistence

## Blocked by

- [03-incremental-discovery.md](./03-incremental-discovery.md)
