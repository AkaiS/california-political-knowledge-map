# California Political Knowledge Map Context

Domain model for mapping political influence networks in California from scraped news articles and other public data sources into a knowledge graph.

## Language

**Publication**:
A structured domain definition representing a news outlet or data source, specifying its identity, crawl parameters, politeness policies, discovery strategies, and tracking metrics such as validation failure points.
_Avoid_: News site, outlet, source site

**Publication Registry**:
A persistent database store (the `publications` table) holding registered Publications, allowing their configurations to be queried, modified, and tracked dynamically at runtime.
_Avoid_: Static registry, config file registry

**Discovery Strategy**:
An interface and implementation defining how article URLs are found for a Publication, such as parsing an XML sitemap or crawling paginated archive listings.
_Avoid_: Crawler type, lookup method

**Discovery State**:
A persistent record stored in the SQLite database that tracks the dynamic operational progress of a Publication's archive crawl (e.g., the last processed page number or sitemap index), allowing crawls to resume.
_Avoid_: Ingestion progress, scrap log, config state

**Listing Page Discovery**:
A discovery method (Strategy A) that crawls configured listing or category pages, extracts all internal hyperlinks, and applies URL filters (path blocklists and anchor text heuristics) to discover candidate article URLs.
_Avoid_: Page scrounger, link list crawl

**Domain Map Discovery**:
A discovery method (Strategy B) that utilizes Crawl4AI's DomainMapper to discover all URLs under a publication's domain and subdomains, filtering them to discover candidate article URLs.
_Avoid_: Domain spider, site mapping

**Politeness Policy**:
A configuration schema defined per Publication that dictates the crawling restrictions for its domain, including custom crawl delays, maximum concurrent requests, and robots.txt conformance rules.
_Avoid_: Rate limit config, block policy

**Concurrent Crawler**:
A component responsible for orchestrating parallel scraping tasks across multiple Publications, ensuring that requests to different hosts occur concurrently while strictly respecting each domain's individual Politeness Policy.
_Avoid_: Batch scraper, multi-threader

**Incremental Scraping**:
A scraping method that retrieves article metadata (like URLs) first and verifies their existence in the database before requesting or downloading the full article bodies, preventing redundant network requests.
_Avoid_: Delta ingestion, double check

**Anchor Text Heuristics**:
A filtering rule applied to discovered listing page links that discards links with short or non-descriptive anchor text to eliminate navigation menu items and index links.
_Avoid_: Link text check, title filter

**Archive Crawler**:
A CLI subcommand (`ca-map scrape-archive`) designed to crawl the historical archives of registered Publications using their Discovery Strategies and tracking progress in the database via the Discovery State, terminating when there are no more pages or when it reaches a configurable historical cutoff (defaulting to 5 years).
_Avoid_: Historical scraper, archive daemon

**Update Scheduler**:
A CLI subcommand (`ca-map update-sources`) meant to be executed by external orchestrators (like `cron` or `launchd`) on a 12-hour interval, which runs the Incremental Scraping pipeline for all registered Publications to discover and download new articles.
_Avoid_: Cron jobs, timer loop, background worker daemon

**Article Validator**:
A component that validates extracted article content by comparing CSS-parsed attributes against a ground-truth baseline (JSON-LD headline, author, publish date, word count) or falling back to heuristic sanity checks (link density and stopword ratio). Articles whose HTML contains no JSON-LD at all are marked unvalidatable rather than failed, since no ground truth exists to validate or heal against.
_Avoid_: Schema checker, parser tester

**Selector Healing Pipeline**:
An asynchronous, LLM-driven process (a Generator/Critic team loop) triggered when a Publication's Validation Circuit Breaker trips, which parses preprocessed cleaned HTML and ground-truth metadata to propose new selectors for developer review.
_Avoid_: Selector fixer, auto-repairer

**Publication Bootstrapper**:
An LLM-driven process that initializes a new Publication by analyzing a sample of raw article HTML files and their JSON-LD metadata to discover selector candidates, presenting them for human verification before registration.
_Avoid_: Source creator, template writer

**Article Selector**:
A CSS selector definition targeting elements of a single article page (title, author, publish date, body text) to extract structured story content.
_Avoid_: Page selector, content parser

**Selector Version**:
A specific iteration of HTML/CSS scraping selectors for a Publication, associated with a success validity window (earliest and latest success fetch dates) to support parsing historical variations of a website's layout.
_Avoid_: Schema revision, css version

**Selector Store**:
The persistent database store (the `publication_selectors` table) holding versioned CSS selectors mapped to execution success windows.
_Avoid_: Selector registry, selector catalog

**Selector Proposal**:
A candidate set of Article Selectors produced by the Selector Healing Pipeline or Publication Bootstrapper, persisted in the SQLite database (the `selector_proposals` table) and awaiting developer review before promotion to the Selector Store.
_Avoid_: Proposal file, selector draft, candidate report

**Raw HTML Store**:
A persistent database store (the `scraped_html_cache` table) holding the raw HTML content of scraped articles to support asynchronous self-healing, offline re-scraping, and validation recovery before being purged after 30 days.
_Avoid_: Page cache, web archive, HTML file cache

**Relevance Filter**:
A multi-stage pipeline component that filters discovered URLs using a path blocklist and evaluates extracted metadata (headlines and descriptions) against target keywords to determine California political relevance.
_Avoid_: Topic classifier, page filter

**Relevance Status**:
The automated classification assigned to a discovered article URL, which determines whether it is scraped (`RELEVANT`), discarded (`IRRELEVANT`), or routed for human review (`INCONCLUSIVE`). `INCONCLUSIVE` is not a human ground-truth label; human labels are binary: `RELEVANT` or `IRRELEVANT`.
_Avoid_: Relevance score, category

**Validation Circuit Breaker**:
A safety mechanism that automatically pauses the validation pipeline for a Publication if its validation failure points reach or exceed the threshold, triggering a single Selector Healing Pipeline run while allowing raw scraping to continue.
_Avoid_: Breaker, validator pause

**Recovery Check**:
An automatic validation check run on the specific article that triggered a Selector Healing Pipeline execution, triggered when a new selector version is approved/promoted, which resets the failure points to 0 and resumes active validation if successful.
_Avoid_: Cache retry, selector sweep

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

**Evaluation Gold Set**:
A versioned collection of human-labeled examples used as the authoritative expected outcomes when evaluating model-backed pipeline components.
_Avoid_: Test fixtures, benchmark data, model labels

**Evaluation Run**:
One recorded execution of an evaluation suite against a specific component, configuration, and Evaluation Gold Set version.
_Avoid_: Test run, benchmark, experiment

**Evaluation Case Result**:
The recorded outcome for one Evaluation Gold Set example within an Evaluation Run, including its scores, timing, and failure details.
_Avoid_: Test result, row, sample output

