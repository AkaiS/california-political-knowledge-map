# 03. Incremental discovery & Raw HTML Store (`ca-map update-sources`)

Labels: completed

## Parent

[Scraping Pipeline PRD](../PRD.md)

## What to build

Create the Raw HTML Store: the `scraped_html_cache` SQLite table with validation statuses `PENDING`, `VALIDATED`, `VALIDATION_FAILED`, and `UNVALIDATABLE`.

Add a `ca-map update-sources` subcommand implementing Listing Page Discovery for all registered Publications: crawl configured listing pages using Crawl4AI link extraction, apply the pre-fetch URL path blocklist (per-publication `url_path_blocklist` with a global fallback) and Anchor Text Heuristics (only follow links with anchor text >= 5 words and >= 25 characters), skip URLs already present in `scraped_html_cache`, `rejected_articles`, or `stories`, then fetch surviving candidates and cache their raw HTML as `PENDING`. Crawling must respect each Publication's Politeness Policy (crawl delay, max concurrency, robots.txt).

In this slice every fetched candidate is cached as `PENDING`; the Relevance Filter classification is layered in by issue 04 (the skip-check against `rejected_articles` should already be in place so 04 slots in cleanly).

## Acceptance criteria

- [x] `scraped_html_cache` table is created on database initialization with the four-status CHECK constraint
- [x] `ca-map update-sources` discovers candidate links from listing pages and filters them through the path blocklist and Anchor Text Heuristics before any fetch
- [x] URLs already known to `scraped_html_cache`, `rejected_articles`, or `stories` are never re-fetched
- [x] Fetched articles are cached as `PENDING` with publication id and scrape timestamp
- [x] Politeness Policy (delay, concurrency, robots.txt) is honored per Publication
- [x] Tests cover link extraction, blocklist filtering, anchor heuristic word/char boundaries, skip-existing behavior, and cache writes (Crawl4AI mocked)

## Blocked by

- [01-publication-registry.md](./01-publication-registry.md)
