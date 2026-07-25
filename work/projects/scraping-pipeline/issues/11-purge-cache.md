# 11. `ca-map purge-cache` retention command

Labels: completed

## Parent

[Scraping Pipeline PRD](../PRD.md)

## What to build

Add a `ca-map purge-cache` subcommand that applies the Raw HTML Store retention policy, intended to be run periodically by an external task scheduler (cron/launchd) — no other command purges implicitly.

Per the PRD's "HTML Cache Retention": null out `raw_html` for `VALIDATED` rows 30 days after their corresponding story is marked `COMPLETED`, and for `UNVALIDATABLE` rows 30 days after their `validation_date`. `VALIDATION_FAILED` rows are never purged (their HTML supports healing) and `PENDING` rows are untouched. The command reports how many rows it purged.

## Acceptance criteria

- [x] Eligible `VALIDATED` rows (story `COMPLETED` more than 30 days ago) have `raw_html` set to NULL while their status row remains
- [x] Eligible `UNVALIDATABLE` rows (validated more than 30 days ago) are purged the same way
- [x] `VALIDATION_FAILED` and `PENDING` rows are never touched
- [x] The command prints a summary of purged row counts and is safe to run repeatedly
- [x] Tests cover each status's eligibility rules, the 30-day boundary, and idempotent re-runs

## Blocked by

- [06-article-validator.md](./06-article-validator.md)
