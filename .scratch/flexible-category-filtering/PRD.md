# Scraping Pipeline: Flexible Category Filtering PRD

Status: ready-for-agent

## Problem Statement

During URL discovery from publication listing pages (e.g., crawling category pages such as `https://calmatters.org/category/housing/`), the system must filter candidate links to ensure they are relevant to the publication. However, the current filtering model is too rigid, causing valid articles to be rejected. Specifically, when crawling `https://calmatters.org/category/housing/`, the system rejects `/housing/homelessness/2026/07/trump-homeless-funding-judge/` because the link's path does not match the listing URL's `/category/housing/` prefix. Similarly, a listing for `/category/politics/` rejects environment stories like `/environment/2026/07/california-gas-prices-july-fourth/` that are linked on the politics page. Additionally, URLs are not normalized, risking duplicate ingestion of the same articles with different marketing/tracking query parameters (e.g., `?utm_source=...`).

## Solution

We will implement a looser, more flexible, publication-dependent category matching filter during the pre-fetch phase of URL discovery.
1. Add a `valid_categories` list to each publication's `discovery_config_json`.
2. When filtering discovered links on a listing page, check if any of the URL's path segments (excluding the last segment, which is the article name) exactly match any of the publication's `valid_categories` (case-insensitive).
3. If `valid_categories` is omitted or empty for a publication, bypass the category check entirely (allowing publications with flat URL structures to crawl all same-domain links).
4. Update the URL resolution utility to normalize URLs by stripping marketing and tracking query parameters (e.g., `utm_*`, `fbclid`, `gclid`, `ref`, `amp`) while preserving critical routing query parameters (like `id` or `p`).

## User Stories

1. As a crawler, I want to filter candidate URLs using the publication's configured `valid_categories`, so that I only fetch articles that belong to target categories.
2. As a crawler, I want the category match check to exclude the last segment of the path, so that keywords in the article's title slug do not cause false category matches.
3. As a developer, I want to configure the list of valid categories per publication in `discovery_config_json`, so that filtering is customized to each news organization's category structure.
4. As a crawler, I want to bypass the category match filter if no `valid_categories` are configured for a publication, so that I can discover articles on publications that use flat URL structures (without category path segments).
5. As a database ingest pipeline, I want all candidate URLs to be normalized (stripping tracking tokens like `utm_source` and `fbclid`) before checking if they exist in the cache or stories table, so that we prevent duplicate fetches and storage of the same article under different tracking URLs.
6. As a crawler, I want to perform exact segment matching against category names, so that substring matches (like `/sports/.../immigration-officer/` matching the category `immigration`) do not cause irrelevant articles to bypass pre-fetch filtering.

## Implementation Decisions

- **Configuration Schema**:
  We will add an optional `valid_categories` array to the JSON schema in the `discovery_config_json` field of the `publications` SQLite table.
- **Link Normalization**:
  The `clean_and_resolve_url` utility function in `src/knowledge_map/utils/scraper.py` will be modified or will call a new helper to strip standard campaign/tracking query parameters (`utm_*`, `fbclid`, `gclid`, `ref`, `amp`) and fragment identifiers, while preserving other query parameters.
- **Category Filter Logic**:
  Implement the exact, case-insensitive segment match in the URL path discovery filter:
  - If `valid_categories` is present: parse the URL path, split it by `/`, drop empty elements, discard the last element (article name), and check if any remaining element matches the set of valid categories exactly.
  - If `valid_categories` is empty or missing: allow all URLs that pass domain and blocklist checks.
- **Precedence of Operations**:
  During link discovery, candidate URLs will be filtered in the following order:
  1. Resolve and normalize the URL.
  2. Same-domain check.
  3. Path blocklist check (which must run before category matching so that blocked sections like `/sports/` are dropped immediately).
  4. Category segment check (if configured).
  5. Anchor heuristics check.

## Testing Decisions

- **Good Test Criteria**:
  - Verify that URLs containing tracking parameters are normalized (e.g. `https://site.org/path?utm_source=feed&p=123` becomes `https://site.org/path?p=123`).
  - Verify that category segment checks exclude the last segment (article slug) and use exact, case-insensitive matches.
  - Verify that when `valid_categories` is empty or omitted, URLs with flat paths or mismatching categories are not filtered out by the category check.
  - Verify that blocklist filtering takes precedence over category matching.
- **Modules to Test**:
  - `clean_and_resolve_url` in [scraper.py](file:///Users/akaisenghor/Projects/california-political-knowledge-map/src/knowledge_map/utils/scraper.py) (normalisation and query parameter filtering).
  - `ListingPageDiscoveryService` / `should_keep_url` helper in [discovery.py](file:///Users/akaisenghor/Projects/california-political-knowledge-map/src/knowledge_map/core/discovery.py) (category filtering, last segment exclusion, flat URL opt-out).
- **Prior Art**:
  - Existing tests in [test_incremental_discovery.py](file:///Users/akaisenghor/Projects/california-political-knowledge-map/tests/test_incremental_discovery.py) test the `PolitenessLimiter`, `url_filtering` (with `should_keep_url`), and mock listing crawl responses. We will extend `test_url_filtering` and add tests for `clean_and_resolve_url` in `test_scraper.py`.

## Out of Scope

- Extracting category tags dynamically from page content using LLMs or machine learning during the *discovery* phase (this remains a metadata-based check during the validation phase).
- Automatic discovery of a publication's categories (valid categories must be configured manually during publication registration).
