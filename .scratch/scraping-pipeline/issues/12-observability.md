# 12. Structured logging, Logfire spans & drift warnings

Status: completed

## Parent

[Scraping Pipeline PRD](../PRD.md)

## What to build

Complete the observability layer across the scraping pipeline per the PRD's "Structured Logging & Telemetry Specifications":

- Structured JSON log fields for discovery stats (`links_found`, `blocklist_filtered`, `anchor_filtered`, `new_candidates_found`), relevance check outcomes, validation outcomes, and circuit-breaker state changes, with every discarded URL recording its precise filter reason (e.g. `blocklist_hit`, `anchor_heuristic_dropped`).
- Custom Logfire spans (e.g. `scrape_publication`, `heal_selectors`) building on the existing telemetry setup, which already instruments Pydantic AI and httpx, so LLM costs and HTTP latencies attach to scraping operations.
- Discovery drift warnings: if a discovery run returns 0 candidate URLs from a `200 OK` response, emit a console warning banner (layout drift or over-restrictive filters). Circuit-breaker trips get the same console warning treatment.

## Acceptance criteria

- [x] Discovery, relevance, validation, and circuit-breaker events emit structured logs with the PRD's named fields, queryable in Logfire
- [x] Every discarded URL logs its specific filter reason
- [x] Custom spans wrap publication scrape runs and healing runs
- [x] A zero-candidate discovery result from a successful response emits a console drift warning; breaker trips emit a console warning banner
- [x] Tests assert log field presence/shape and warning emission for the drift and trip cases

## Blocked by

- [05-archive-crawl.md](./05-archive-crawl.md)
- [07-circuit-breaker.md](./07-circuit-breaker.md)
