# 0003. Decoupled Scraping, Versioned Selectors, and Self-Healing Ingestion

We decided to decouple article scraping from the GraphRAG ingestion pipeline. A dynamic `PublicationRegistry` (stored in the SQLite database) tracks publication metadata, politeness policies, and discovery strategies, but *excludes* HTML/CSS parsing selectors. Website parsing schemas change frequently, so selectors are stored dynamically in a SQLite `Selector Store` as versioned records (`Selector Version`) mapped to execution success windows (`earliest_success_date` to `latest_success_date` based on successfully parsed article fetch dates).

To filter out irrelevant topics (like sports, recipes, or lifestyle articles) on broad publications during URL discovery, we use a two-phase relevance filter:
1. **Pre-fetch URL path filter:** Discard URLs matching a path segment blocklist (e.g., `["/sports/", "/recipes/"]`) stored in each publication's registry config.
2. **Metadata keyword check:** Evaluate title and description keywords (extracted from JSON-LD or meta tags) against a global list of California political terms. If matches are found, it is classified as `RELEVANT`. If inconclusive, it is cached as `INCONCLUSIVE` to pass to a future logistic regression embeddings classifier. Otherwise, it is classified as `IRRELEVANT` and discarded.

To ensure data quality and detect layout drift, an `Article Validator` compares the CSS-extracted text and metadata against ground truth extracted from JSON-LD structure in the HTML `<head>`. It enforces title, author, and date matching, and compares body word counts within a `[0.9, 1.1]` ratio when `wordCount` is present. If `wordCount` is absent, it falls back to structural sanity checks (link density and stopword ratio) to verify natural language prose. Articles with no JSON-LD at all are marked `UNVALIDATABLE` rather than failed: they accrue no failure points and are never healing targets, because selector regeneration cannot manufacture missing ground truth.

We decouple scraping from validation to ensure crawlers continue caching HTML pages even if selectors drift. When validation fails, the cache record validation status is set to `VALIDATION_FAILED` and the publication's failure points increase (3 points for ground-truth mismatches, 1 point for fallback failures). If these points reach or exceed 10 points, validation is `PAUSED` for that publication, while scraping continues. Any successful validation—using current selectors—immediately resets the failure points to 0.

An asynchronous `Selector Healing Pipeline` (powered by a Generator/Critic LLM loop capped at 3 iterations) is triggered only when the circuit breaker trips — not on individual validation failures — so isolated transient failures never spend LLM calls; we accept losing occasional articles in exchange. It generates selector proposals from the cached failed HTML and JSON-LD ground truth, persisting them in the SQLite database for review. A human must verify and approve the proposed selectors before they are activated. A similar `Publication Bootstrapper` loop is used to initialize new Publications.

## Considered Options

* **Selectors in configuration file**: Storing selectors directly in a static configuration file. This makes it difficult to maintain selector history or support different selectors for different periods of time without code deployment.
* **Heuristic baseline parsing (newspaper4k)**: Using heuristic libraries to extract baselines. Rejected because newspaper4k is highly inconsistent and prone to missing bylines, dates, or body sections, causing high false-failure rates. JSON-LD provides an authoritative, developer-published ground truth.
* **Registry in DB vs Config File**: Storing publication metadata (URLs, crawl rules, discovery strategies) in a SQLite table vs a local configuration file. We chose a SQLite table to unify all operational, stateful, and configuration data in the database.
* **BM25 Relevance filter**: Scoring relevance against a local corpus. Rejected because BM25 ranking is corpus-dependent and doesn't directly answer "is this a California political article?", and requires maintaining a text corpus.
* **Fully Autonomous Healing**: Activating LLM-generated selectors automatically. This was rejected in favor of human verification to prevent malformed or noisy HTML extractions from entering the knowledge graph.

## Consequences

* **Data Integrity**: Articles are validated against JSON-LD ground truth, preventing layout drift and boilerplate text from contaminating the database.
* **Robust Selector Resolution**: Using success windows and proximity matching allows the scraper to select the most appropriate selectors for any fetch date, with automatic fallback through historical versions if validation fails.
* **Resiliency to Layout Changes**: Website design changes do not halt scraping. Decoupled scraping ensures raw HTML pages are cached continuously while the circuit breaker prevents LLM/API call waste on broken validation loops.
* **HTML Storage Efficiency**: Storing raw HTML indefinitely for failures (supporting healing) while purging raw HTML for successfully processed pages after 30 days keeps database growth bounded.

