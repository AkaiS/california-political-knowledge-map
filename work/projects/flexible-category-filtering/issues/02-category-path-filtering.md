# 02. Per-Publication Category Path Filtering

Labels: completed

## Parent

[PRD.md](../PRD.md)

## What to build

We need a flexible, publication-dependent category path matching filter that runs pre-fetch during URL discovery.

Instead of requiring strict path prefix matching, the crawler should check if any path segment (excluding the last segment, which is the article slug/name) matches the publication's valid categories list. If no categories are configured for the publication, the category check must be bypassed entirely (enabling support for flat URL structures).

### Category Filter Rules
1. **Configuration**: Support an optional `valid_categories` list (array of strings) in the publication's `discovery_config_json`.
2. **Opt-Out (Flat structures)**: If `valid_categories` is omitted or empty, skip the category check.
3. **Exact Segment Match**: Split the URL path by `/`, drop empty elements, and discard the last element (the article name). Perform a case-insensitive, exact equality check on each remaining segment against the `valid_categories` set.
4. **Precedence**: This filter must run after the domain and blocklist checks, but before the anchor heuristics filter.

## Acceptance criteria

- [x] `valid_categories` list is correctly parsed from the publication's `discovery_config_json`.
- [x] Category segment matching ignores the final segment (the article name slug) of the URL path.
- [x] Category segment matching uses exact, case-insensitive matches for the preceding segments (e.g. `/housing/` matches category `housing`, but `/sports/.../immigration-officer/` does not match `immigration`).
- [x] If `valid_categories` is not configured or is empty, URLs with flat paths or mismatching paths are not filtered out by this check.
- [x] Discarded URLs due to category mismatches are logged with a structured log containing `filter_reason = 'category_mismatch'`.
- [x] Unit tests cover exact segment matching, last segment exclusion, bypass behavior when list is empty, and proper precedence (blocklist checked first).

## Blocked by

- [01-url-normalization.md](./01-url-normalization.md)
