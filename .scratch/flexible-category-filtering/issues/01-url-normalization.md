# 01. URL Normalization & Tracking Token Sanitization

Status: completed

## Parent

[PRD.md](../PRD.md)

## What to build

We need to sanitize and normalize discovered URLs during the pre-fetch discovery phase to prevent duplicate fetches, caching, and ingestion of the same articles with different marketing or tracking query parameters (e.g. `?utm_source=...` or `?fbclid=...`).

Modify the URL resolution logic to strip standard marketing/tracking query parameters and fragment identifiers, while preserving necessary query parameters required for page routing (e.g. `id` or `p`).

### Sanitization Rules
1. **Strip standard tracking/campaign parameters (case-insensitive)**:
   - `utm_source`, `utm_medium`, `utm_campaign`, `utm_term`, `utm_content`
   - `fbclid`, `gclid`
   - `ref`, `amp`
2. **Keep routing query parameters**:
   - Preserve parameters like `id`, `p`, `v`, `article_id`.
3. **Strip fragment identifiers**:
   - Always remove fragment anchors (e.g., `#ref`, `#comments`).

## Acceptance criteria

- [x] `clean_and_resolve_url` in `src/knowledge_map/utils/scraper.py` strips all standard marketing, referral, and tracking query parameters (`utm_*`, `fbclid`, `gclid`, `ref`, `amp`).
- [x] Non-tracking query parameters (like `id` or `p` for routing) are preserved in the resolved URL.
- [x] Fragment/hash components (e.g. `#comments`) are stripped from the resolved URL.
- [x] Unit tests verify normalization of URLs with mixed routing and tracking parameters (e.g. `https://test.com/path?utm_source=feed&id=456#anchor` resolves to `https://test.com/path?id=456`).

## Blocked by

None - can start immediately
