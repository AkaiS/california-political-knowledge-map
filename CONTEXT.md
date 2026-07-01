# California Political Knowledge Map Context

Domain model for mapping political influence networks in California from scraped news articles and other public data sources into a knowledge graph.

## Language

**Publication**:
A structured domain definition representing a news outlet or data source, specifying its name, base URL, crawl politeness rules (e.g., delay, robots.txt conformance), and the HTML/CSS parsing schemas required to extract its listings and article bodies.
_Avoid_: News site, outlet, source site

**Publication Registry**:
A persistent database store (a SQLite table) holding registered Publications, specifying their base URLs, Politeness Policies, Discovery Strategies, and crawl parameters.
_Avoid_: Static registry, config file registry

**Discovery Strategy**:
An interface and implementation defining how article URLs are found for a Publication, such as parsing an XML sitemap or crawling paginated archive listings.
_Avoid_: Crawler type, lookup method

**Discovery State**:
A persistent record stored in the SQLite database that tracks the dynamic operational progress of a Publication's archive crawl (e.g., the last processed page number or sitemap index), allowing crawls to resume.
_Avoid_: Ingestion progress, scrap log, config state

**Politeness Policy**:
A configuration schema defined per Publication that dictates the crawling restrictions for its domain, including custom crawl delays, maximum concurrent requests, and robots.txt conformance rules.
_Avoid_: Rate limit config, block policy

**Concurrent Crawler**:
A component responsible for orchestrating parallel scraping tasks across multiple Publications, ensuring that requests to different hosts occur concurrently while strictly respecting each domain's individual Politeness Policy.
_Avoid_: Batch scraper, multi-threader

**Incremental Scraping**:
A scraping method that retrieves article metadata (like URLs) first and verifies their existence in the database before requesting or downloading the full article bodies, preventing redundant network requests.
_Avoid_: Delta ingestion, double check

**Archive Crawler**:
A CLI subcommand (`ca-map scrape-archive`) designed to crawl the historical archives of registered Publications using their Discovery Strategies and tracking progress in the database via the Discovery State, terminating when there are no more pages or when it reaches a configurable historical cutoff (defaulting to 5 years).
_Avoid_: Historical scraper, archive daemon

**Update Scheduler**:
A CLI subcommand (`ca-map update-sources`) meant to be executed by external orchestrators (like `cron` or `launchd`) on a 12-hour interval, which runs the Incremental Scraping pipeline for all registered Publications to discover and download new articles.
_Avoid_: Cron jobs, timer loop, background worker daemon

**Article Validator**:
A component that validates scraped article content using structural constraints and compares it against a heuristic baseline (provided by `newspaper4k`) to detect extraction failures or layout drift.
_Avoid_: Schema checker, parser tester

**Selector Healing Pipeline**:
An LLM-driven process triggered automatically when an article fails validation, which analyzes the raw HTML and the heuristic baseline to generate new selector candidates, presenting a preview for human verification before activation.
_Avoid_: Selector fixer, auto-repairer

**Publication Bootstrapper**:
An LLM-driven process that initializes a new Publication by analyzing a sample of raw article HTML files and their heuristic baselines to discover selector candidates, presenting them for human verification before registration.
_Avoid_: Source creator, template writer

**Selector Version**:
A specific iteration of HTML/CSS scraping selectors for a Publication, associated with a time validity window (`valid_from` and `valid_to` timestamps) to support parsing historical variations of a website's layout.
_Avoid_: Schema revision, css version

**Selector Store**:
The persistent database store (a SQLite table) holding all Selector Versions, allowing the crawler to query the active selectors for any article's publication or crawl date.
_Avoid_: Selector registry, selector catalog

**Raw HTML Store**:
A persistent store (e.g., local files or a dedicated SQLite table) that records the exact raw HTML content of scraped articles, primarily used to support asynchronous self-healing, debugging, and offline re-scraping when selectors change.
_Avoid_: Page cache, web archive

**Relevance Document**:
A concatenated text representation of a discovered page's metadata (including title, meta description, keywords, and tags) used to run local BM25 relevance filters before committing to a full article body download.
_Avoid_: Search index, article body copy

**Source Article**:
A strongly-typed domain model representing a scraped news story or report containing political coverage and influence data.
_Avoid_: News piece, document, post, feed

**Article Chunk**:
A structured segment of a Source Article's text, representing a smaller, contiguous block used to optimize Entity Extraction and store vector embeddings.
_Avoid_: Fragment, snippet, text slice, part

**Extraction Prompt**:
The instructions and guidelines loaded from an external file (`extraction_prompt.txt`) and fed to the Language Model (LLM) to identify and structure nodes and relationships from a Source Article's text.
_Avoid_: Prompt, template, instruction set


**Entity Extraction**:
The process of identifying specific real-world entities (political actors, organizations, public policy measures) and the semantic relationships between them from unstructured article text.
_Avoid_: Named Entity Recognition, parsing, data extraction

**Influence Graph Playground**:
The interactive command-line interface implemented in `playground.py` used to execute prompt-guided entity extraction on Source Articles, enabling the user to inspect and refine the schema before Neo4j ingestion.
_Avoid_: Test environment, testing script, sandbox, trial run

**Graph Database Adapter**:
The database adapter protocol and its concrete implementation (Neo4jAdapter) that abstracts the Neo4j database, managing connections, index validation, and ingestion of Source Articles, Article Chunks, and Extracted Entities.
_Avoid_: Database manager, Neo4j client, direct driver wrapper



**Entity Resolution**:
The process of identifying, measuring semantic similarity between, and merging nodes that represent the same real-world political actor, organization, or measure.
_Avoid_: Deduplication, merging, cleaning, string matching

**Coreference Resolution**:
The process of resolving pronouns and referring expressions in a Source Article's text to their canonical entity names before or during Entity Extraction to prevent information loss across Article Chunks.
_Avoid_: Pronoun matching, reference linking

**Annotated Article**:
A Source Article that has been pre-processed to explicitly tag pronouns and referring expressions with their canonical entity targets using markup (e.g. `<ref>` tags).
_Avoid_: Tagged text, parsed story

**Coreference Critic**:
An LLM agent that reviews and validates the annotated coreferences in an Annotated Article to ensure semantic accuracy and prevent incorrect reference mapping before chunking.
_Avoid_: Critic agent, checker, validator

**Story Pipeline**:
A synchronous pipeline coordinator that orchestrates the coreference resolution, chunking, embedding generation, entity extraction, and persistence steps for a Source Article.
_Avoid_: Ingestion runner, story processor

**Pipeline Result**:
A structured domain model returning the outcome of a Story Pipeline execution, containing the processed chunks and extracted entities (useful for dry runs and validation).
_Avoid_: Processing report, output dict

**Embedding Adapter**:
The adapter protocol and its concrete implementation that handles vector embedding calculations and dimension checks for Article Chunks.
_Avoid_: Embedder helper, vector utility

**Coreference Adapter**:
The adapter protocol and its concrete implementation that handles pronoun resolution and entity tagging on a Source Article.
_Avoid_: Resolver wrapper, coref helper

**Entity Extraction Adapter**:
The adapter protocol and its concrete implementation that extracts entities and relationships from Article Chunks.
_Avoid_: Extractor model, agent helper




