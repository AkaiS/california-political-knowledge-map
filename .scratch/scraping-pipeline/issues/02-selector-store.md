# 02. Selector Store & success-window proximity selection

Status: ready-for-agent

## Parent

[Scraping Pipeline PRD](../PRD.md)

## What to build

Create the Selector Store: the `publication_selectors` SQLite table holding versioned Article Selectors (title, author, date, body as JSON) mapped to success windows (`earliest_success_date`, `latest_success_date`).

Implement Selector Version selection per the PRD's "Selector Selection & Fallback" rules: for an article fetched at date D, compute each version's distance to its success window (0 if inside the window, otherwise distance to the nearest boundary), try versions in ascending distance order, widen the winning version's window on success (`earliest = min(earliest, D)`, `latest = max(latest, D)`), and fall through to the next-closest version on failure. Expose an API that the Article Validator (issue 06) can consume: given a publication and fetch date, yield selector versions in try-order.

## Acceptance criteria

- [ ] `publication_selectors` table is created on database initialization with the PRD schema
- [ ] Selector Versions can be inserted with an initial success window and retrieved per Publication
- [ ] Selection returns versions ordered by success-window proximity for a given fetch date, with distance 0 for in-window dates
- [ ] A successful extraction widens the version's success window; a failure falls back to the next-closest version
- [ ] Tests cover proximity ordering (in-window, before-window, after-window, ties), window widening, and fallback exhaustion

## Blocked by

- [01-publication-registry.md](./01-publication-registry.md)
