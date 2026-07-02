# 0004. Listing Discovery via Link Extraction and Filtering

We decided to drop layout-dependent listing CSS selectors in favor of a robust, general-purpose URL discovery pipeline. The discovery flow uses Crawl4AI's link extraction for recent/incremental crawls (Strategy A) and Crawl4AI's `DomainMapper` for historical/archive crawls (Strategy B). Discovered URLs are filtered using a pre-fetch path blocklist and anchor text heuristics, followed by a metadata relevance check.

## Considered Options

* **CSS-Based Listing Page Selectors**: Maintaining distinct CSS selectors for listing pages. This was rejected because listing layouts change frequently, leading to crawler breakage. Writing and maintaining selectors for listing pages (and healing them via LLM loops) introduces excessive development overhead and token costs without JSON-LD ground truth to validate against.
* **Simple Sitemap-Only Crawls**: Relying exclusively on sitemaps for discovery. Rejected because many target news publications in California have broken, incomplete, or nonexistent XML sitemaps, which would prevent us from scraping their archives or getting timely updates.
* **Deep crawling (BFS/DFS)**: Recursively following links. Rejected because it easily leads to infinite loops, high resource consumption, and scraping duplicate/non-article content.

## Consequences

* **Reduced Selector Maintenance**: The `Selector Store` and the `Selector Healing Pipeline` are restricted entirely to article page selectors (title, author, publish date, body), which can be strictly validated against JSON-LD.
* **Crawl Overhead for Relevance Filtering**: Since metadata is not fully present on the listing page, the crawler must fetch the full HTML of candidate URLs to run the `Relevance Filter` (checking headline/description keywords). However, this overhead is mitigated because we check if the URL already exists in the database before scraping.
* **Higher Discovery Robustness**: Combining path blocklisting, anchor text length heuristics (e.g. discarding short/non-descriptive link text), and domain validation allows the scraper to filter out navigation menus, footers, and utility links reliably without needing CSS selectors.
