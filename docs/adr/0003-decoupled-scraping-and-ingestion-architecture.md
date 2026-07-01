# 0003. Decoupled Scraping, Versioned Selectors, and Self-Healing Ingestion

We decided to decouple article scraping from the GraphRAG ingestion pipeline. A dynamic `PublicationRegistry` (stored in the SQLite database) tracks publication metadata, politeness policies, and discovery strategies, but *excludes* HTML/CSS parsing schemas. Website parsing schemas change frequently, so selectors are stored dynamically in a SQLite `Selector Store` as versioned records (`Selector Version`) mapped to time validity windows (`valid_from` to `valid_to`).

To filter out irrelevant topics (like sports, recipes, or lifestyle articles) on broad publications during URL discovery, we use BM25 keyword relevance scoring against a metadata-constructed `Relevance Document` (concatenating the article's title, meta description, HTML keywords, and sections). We apply a single, robust, global California politics query (stored in our application config) universally across all publications to ensure consistent scoring. If the score falls below a threshold, the article is discarded before extracting the main body text, running validator checks, or saving it to SQLite.

To ensure data quality and detect layout drift, an `Article Validator` compares the CSS-extracted article text and metadata against a heuristic baseline generated using `newspaper4k`. It enforces strict presence checks for title, author, and date, and verifies that the extracted body text length is within a configurable percentage of the baseline. 

If validation fails, the crawler stores the raw page content in a `Raw HTML Store` and flags the article as `VALIDATION_FAILED`. An asynchronous `Selector Healing Pipeline` (powered by a Generator/Critic LLM loop) analyzes the failed HTML and baseline to propose new CSS selectors. A human must verify and approve the proposed selectors before they are activated in the Selector Store and the raw HTML is re-parsed for ingestion. A similar `Publication Bootstrapper` loop is used to initialize new Publications.

## Considered Options

* **Selectors in configuration file**: Storing selectors directly in a static configuration file. This makes it difficult to maintain selector history or support different selectors for different periods of time without code deployment.
* **Automatic Fallback to Newspaper4k**: Using `newspaper4k` to extract the article immediately upon CSS validation failure. This was rejected because GraphRAG entity and relationship extraction is expensive, and we want to ensure only high-quality, cleanly parsed articles are ingested.
* **Registry in DB vs Config File**: Storing publication metadata (URLs, crawl rules, discovery strategies) in a SQLite table vs a local configuration file. We chose a SQLite table to unify all operational, stateful, and configuration data in the database, allowing dynamic commands to register, configure, and bootstrap new publications at runtime.
* **Global vs Per-Publication Relevance Query**: Storing a relevance query per publication. This was rejected in favor of a single, robust, global California politics query, as our project focuses on a single subject domain and a global query ensures consistency.
* **Title-only Relevance Checks**: Scoring relevance using only the headline. Headline titles are often sensational or narrative, lacking political keywords (like names of bills or state departments). Combining title, description, keywords, and sections into a unified Relevance Document provides a much more robust match.
* **Fully Autonomous Healing**: Activating LLM-generated selectors automatically. This was rejected in favor of human verification to prevent malformed or noisy HTML extractions from entering the knowledge graph.

## Consequences

* **Data Integrity**: Articles are validated against a heuristic baseline before ingestion, preventing boilerplate text (navigation bars, ads, comments) from contaminating the database.
* **Relevance Filtering**: The pipeline avoids scraping and storing irrelevant, non-political news stories, optimizing storage and downstream LLM API costs.
* **Resiliency to Layout Changes**: Website design changes do not crash the pipeline. Failed scrapes are stored as raw HTML, allowing the system to self-heal and re-parse the historical HTML once new selectors are approved.
* **Historical Accuracy**: Articles from different eras of a website's layout history can be parsed correctly using the Selector Store's time-range query.
