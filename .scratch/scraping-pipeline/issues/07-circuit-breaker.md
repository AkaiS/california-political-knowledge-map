# 07. Validation Circuit Breaker (points, trip, pause, reset)

Status: ready-for-agent

## Parent

[Scraping Pipeline PRD](../PRD.md)

## What to build

Layer the Validation Circuit Breaker onto the Article Validator: accumulate weighted failure points per Publication (3 for ground-truth mismatches, 1 for fallback failures, weighted by the best attempt across selector versions; `UNVALIDATABLE` articles accrue nothing), reset points to 0 on any successful validation while `ACTIVE`, and trip when points reach or exceed 10 — setting `validation_paused` and recording which `VALIDATION_FAILED` article tripped the breaker (the future healing target for issue 08).

While `PAUSED`: routine validation of `PENDING` entries is skipped entirely, crawling and caching continue untouched, and transient successes from manual runs do not reset points or unpause. Tripping the breaker is the only automatic trigger point for the Selector Healing Pipeline; expose that trigger as a seam for issue 08 to fill.

## Acceptance criteria

- [ ] Failure points accumulate with correct weights and best-attempt classification; `UNVALIDATABLE` articles add no points
- [ ] A successful validation during `ACTIVE` resets points to 0
- [ ] Points reaching 10 set the Publication to `PAUSED` and record the tripping article
- [ ] While `PAUSED`, `PENDING` validation is skipped but `update-sources` / `scrape-archive` continue caching raw HTML
- [ ] Successes while `PAUSED` do not reset points or unpause
- [ ] A healing-trigger seam fires exactly once per trip (stubbed until issue 08)
- [ ] Tests cover point accumulation/reset, trip threshold, pause skip behavior, and paused-state success handling

## Blocked by

- [06-article-validator.md](./06-article-validator.md)
