# 05. Archive crawl & Discovery State (`ca-map scrape-archive`)

Labels: completed

## Parent

[Scraping Pipeline PRD](../PRD.md)

## What to build

Add the Archive Crawler: a `ca-map scrape-archive` subcommand implementing Domain Map Discovery via Crawl4AI's `DomainMapper`, with resumable progress tracked in the `publication_discovery_state` SQLite table (Discovery State, schema in the PRD).

The crawl discovers URLs under a Publication's domain, applies the pre-fetch path blocklist and the Relevance Filter from issue 04 (Anchor Text Heuristics are bypassed — no anchor text is available in domain mapping), caches relevant articles as `PENDING`, and terminates at the configurable historical cutoff (default 5 years, per-publication `archive_cutoff_years`). Interrupted crawls resume from the persisted Discovery State rather than restarting.

## Acceptance criteria

- [x] `publication_discovery_state` table is created on database initialization with the PRD schema
- [x] `ca-map scrape-archive` discovers URLs via `DomainMapper`, applies blocklist and relevance filtering, and caches relevant articles as `PENDING`
- [x] Anchor Text Heuristics are not applied on this path
- [x] Progress persists to Discovery State during the crawl, and a re-run resumes from it instead of starting over
- [x] The crawl stops at the configured historical cutoff
- [x] Tests cover domain-mapping discovery (mocked), Discovery State persistence and resumption, and cutoff termination

## Blocked by

- [04-relevance-filter.md](./04-relevance-filter.md)
