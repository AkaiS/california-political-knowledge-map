# 06. Article Validator (JSON-LD grounding, `UNVALIDATABLE`, `stories` handoff)

Status: completed

## Parent

[Scraping Pipeline PRD](../PRD.md)

## What to build

Implement the Article Validator as a process decoupled from scraping: it reads `PENDING` entries from the Raw HTML Store, extracts each article using Selector Versions supplied in try-order by the Selector Store (issue 02), and validates the extraction against JSON-LD ground truth per the PRD's Validation Rules:

- Title: case-insensitive edit distance ratio >= 0.90 against the JSON-LD headline.
- Author: normalize both sides (strip filler words, split on commas and "and", case-insensitive), then match each JSON-LD author via Damerau-Levenshtein similarity >= 0.90; accept as-is when JSON-LD has no author.
- Date: same UTC calendar day as `datePublished`, resolving timezone offsets.
- Body: word-count ratio within [0.9, 1.1] when JSON-LD `wordCount` exists; otherwise fallback sanity checks (link density < 0.15, stopword ratio > 0.25).

Articles with no JSON-LD at all are marked `UNVALIDATABLE` and skipped — they are never healing or Recovery Check targets. Successful validations mark the cache row `VALIDATED` and insert the extracted story into the existing `stories` table as `UNPROCESSED` (the handoff to the ingestion pipeline). Failures after exhausting all Selector Versions mark the row `VALIDATION_FAILED`. Failure-point accounting and pause behavior are layered on by issue 07; this slice should surface each failure's type and best-attempt weight so 07 can consume it.

## Acceptance criteria

- [x] `PENDING` cache entries are validated using Selector Versions in proximity order with fallback
- [x] All four validation rules (title, author normalization + Damerau-Levenshtein, UTC date, word-count ratio with fallback sanity checks) behave per the PRD
- [x] Articles missing JSON-LD entirely are marked `UNVALIDATABLE` and excluded from failure handling
- [x] Valid articles are marked `VALIDATED` and appear in `stories` as `UNPROCESSED`; exhausted failures are marked `VALIDATION_FAILED` with a best-attempt failure classification
- [x] Tests cover every comparison rule with edge cases (multi-author strings, timezone offsets, missing `wordCount`, missing JSON-LD) using mocked JSON-LD structures

## Blocked by

- [02-selector-store.md](./02-selector-store.md)
- [03-incremental-discovery.md](./03-incremental-discovery.md)
