# Restore HTML for relevant articles that lack it

Labels: ready-for-agent

## Parent

[Pipeline Stage Ownership: Validation, Relevance, and Raw HTML Lifecycle](../PRD.md)

## What to build

Raw HTML becomes recoverable rather than durable. A re-fetch stage restores it on
demand for any article that is relevant but holds no content — whether because it
was purged, or because a relevance reversal queued it for extraction it had never
received.

Re-fetch selects relevant articles with no raw HTML, no Story row, and a fetch
status that is either absent or not a terminal 4xx. The Story-row predicate is
what prevents re-downloading the entire completed corpus once raw HTML is deleted
on ingestion. The recorded status is what stops permanently dead URLs from being
retried forever while transient failures remain retryable.

Its writer touches raw HTML, the scrape timestamp, and the fetch status, and
nothing else. It must not reuse the discovery cache writer, which replaces whole
rows with relevance defaults and would destroy exactly the label that requested
the re-fetch.

Re-fetch runs before the validation loop within the same invocation, so recovered
articles are validated in one pass rather than requiring a second command. It is
also exposed standalone. The crawler logic is extracted from the discovery
service and shared by both callers; only the persistence call differs.

## Acceptance criteria

- [ ] Re-fetch selects relevant articles that have no raw HTML and no Story row.
- [ ] Re-fetch does not select an article that already has a Story row.
- [ ] Re-fetch does not select an article whose recorded fetch status is a terminal 4xx, and does select one whose status is a 5xx or absent.
- [ ] Every fetch records its HTTP status, including failures.
- [ ] A restore preserves `relevance_status`, `relevance_label_source`, `headline`, `description`, and `embedding` unchanged.
- [ ] Running the validation command re-fetches and then validates in a single invocation, so a purged relevant article ends the run with a Story.
- [ ] Re-fetch is invocable on its own.
- [ ] Discovery and re-fetch share one crawler implementation and differ only in how they persist the result.
- [ ] The full deterministic test suite passes.

## Blocked by

- 03 — Default relevance to PENDING and record fetch status.
- 05 — Enforce the story invariant in the validation loop.
