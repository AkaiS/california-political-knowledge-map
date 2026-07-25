# 09. `ca-map review-selectors`, promotion & Recovery Check

Labels: completed

## Parent

[Scraping Pipeline PRD](../PRD.md)

## What to build

Add a `ca-map review-selectors` subcommand: the Human Approval Seam. It reads unresolved Selector Proposals from the database, previews the content each proposal extracts from the cached raw page, and prompts y/n to resolve the row (`APPROVED` or `REJECTED`, setting `resolved_at`). A `--manual <path_to_json_file>` flag bypasses the LLM proposal flow and promotes developer-specified selectors; the file must name the validation-failed article to test against.

Promotion (approved or manual) registers the selectors as a new Selector Version — success window initialized to the recovery article's fetch date — and runs the Recovery Check on the article that triggered healing. Only a passing Recovery Check resets failure points to 0 and sets validation back to `ACTIVE`; there is no force bypass. Once `ACTIVE`, the validator prioritizes previously `VALIDATION_FAILED` articles ahead of newer `PENDING` ones.

## Acceptance criteria

- [x] Unresolved proposals are listed with an extraction preview against the cached page, and y/n input marks the row `APPROVED` or `REJECTED` with `resolved_at`
- [x] Approval registers a Selector Version with its success window seeded from the recovery article's fetch date
- [x] The Recovery Check runs on the triggering article; success resets points to 0 and unpauses, failure leaves the Publication `PAUSED`
- [x] `--manual` promotes selectors from a JSON file and enforces the same Recovery Check with no bypass
- [x] After unpausing, `VALIDATION_FAILED` articles are validated before newer `PENDING` articles
- [x] Tests cover the review flow, promotion, Recovery Check pass/fail paths, manual promotion, and post-recovery prioritization

## Blocked by

- [02-selector-store.md](./02-selector-store.md)
- [08-selector-healing-pipeline.md](./08-selector-healing-pipeline.md)
