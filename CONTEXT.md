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

**Raw HTML Refetch**:
The stage that fetches an article's raw HTML again on demand, for articles that are `RELEVANT` but hold no content in the Raw HTML Store because it was deleted on Story creation or expired at 30 days. It makes retention recoverable rather than lossy: it rewrites only the raw HTML, Fetch Status, and scraped_at, never Relevance Status or Validation Status, and it succeeds only while the URL is still reachable.
_Avoid_: Restore, HTML restore, re-fetch, re-scrape, recovery

**Relevance Filter**:
A multi-stage pipeline component that filters discovered URLs using a path blocklist and evaluates extracted metadata (headlines and descriptions) against target keywords to determine California political relevance.
_Avoid_: Topic classifier, page filter

**Relevance Status**:
The California-political-relevance decision recorded against a cached article, which determines whether it is extracted into a Story (`RELEVANT`), discarded (`IRRELEVANT`), or routed for human review (`INCONCLUSIVE`). `PENDING` is the absence of a decision rather than a decision: it is the default for a newly cached article and the only status that admits classification, so no settled decision is ever recomputed. `INCONCLUSIVE` is not a human ground-truth label; human labels are binary: `RELEVANT` or `IRRELEVANT`.
_Avoid_: Relevance score, category, unclassified, PENDING_RELEVANCE

**Relevance Label Source**:
The provenance of an article's Relevance Status, naming which stage decided it: the keyword-and-blocklist Relevance Filter (`KEYWORD`), the LLM classifier agent (`LLM`), the trained relevance classifier (`MODEL`), or a person in manual review (`HUMAN`). It is the authority ordering, not a description: a `HUMAN` label is ground truth and no automated stage may overwrite it, which is why the relevance writer reports back the source and status actually persisted rather than the ones attempted.
_Avoid_: Classifier name, label type, labeled_by, confidence

**Validation Status**:
The record of whether extracted content is held for a cached article, valid exactly when a Story row exists for that URL: awaiting or queued for extraction (`PENDING`), extracted and stored (`VALIDATED`), extracted but contradicting its ground-truth baseline (`VALIDATION_FAILED`), or holding no JSON-LD to validate against (`UNVALIDATABLE`). It answers only that question — it carries no relevance meaning, and only the validation stage writes it.
_Avoid_: Article state, processing status, pipeline stage, scrape status

**Fetch Status**:
The HTTP status code recorded against a cached article by the fetch that last attempted it, retained after its raw HTML is purged so that recovery can distinguish a permanently dead URL (terminal 4xx, abandoned) from a transient failure or an unattempted URL (5xx or absent, retryable). It is the status of the last response in a redirect chain, not the first. A fetch that returned no article records the status it got, or none at all, rather than a successful one.
_Avoid_: Response code, error code, scrape result, http_code

**Validation Circuit Breaker**:
A safety mechanism that automatically pauses the validation pipeline for a Publication if its validation failure points reach or exceed the threshold, triggering a single Selector Healing Pipeline run while allowing raw scraping to continue.
_Avoid_: Breaker, validator pause

**Recovery Check**:
An automatic validation check run on the specific article that triggered a Selector Healing Pipeline execution, triggered when a new selector version is approved/promoted, which resets the failure points to 0 and resumes active validation if successful.
_Avoid_: Cache retry, selector sweep

**Story**:
A strongly-typed domain model holding the content extracted from one validated article — title, author, published date, body, and the hyperlinks found in that body — persisted in the SQLite database (the `stories` table). A Story row exists exactly when the article's Validation Status is `VALIDATED`, and only the validation stage writes it. It is the record of what was extracted; the Source Article is the ingestion input built from it.
_Avoid_: Article, extracted article, document, story dict

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
The process of identifying the canonical entities named by pronouns and referring expressions in a Source Article and applying accepted Mention Spans before Entity Extraction, so references remain meaningful across Article Chunks.
_Avoid_: Pronoun matching, reference linking

**Mention Span**:
A structured coreference assertion identifying a pronoun or referring expression in a numbered sentence, its one-based occurrence within that sentence, and the canonical entity it denotes. It is the unit retained or discarded by Coreference Resolution and judged by the Coreference Critic.
_Avoid_: Coreference tag, tagged reference, annotation

**Coreference Critic**:
An LLM agent that returns an accept-or-reject verdict for each Mention Span and a reason for rejected spans, so only semantically supported references are applied before chunking.
_Avoid_: Critic agent, checker, validator

**Coreference Resolution Run**:
The outcome of resolving one Source Article: the resolved text, the numbered sentences shown to the annotator, every Mention Span the model returned, and each Mention Span's outcome. It is what the Coreference Adapter returns, what a coreference failure carries, and what the Dead Letter Queue records.
_Avoid_: Resolution result, coref run, annotation run

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
The adapter protocol and its concrete implementation that resolves Mention Spans in a Source Article and returns the resolved text together with each Mention Span's outcome to the Story Pipeline.
_Avoid_: Resolver wrapper, coref helper

**Entity Extraction Adapter**:
The adapter protocol and its concrete implementation that extracts entities and relationships from Article Chunks.
_Avoid_: Extractor model, agent helper

**News Ontology**:
The closed ontology of the structures a Source Article can actually produce — the labels, sub-labels, per-label properties, relationships, and Policy Area vocabulary that news prose supports. It is a subset of the primary ontology (`ontology.md`), which remains the authored whole, and it is the only thing extraction output is checked against.
_Avoid_: Schema, extraction schema, LLM schema, ontology subset

**Shortcut Rule**:
A declaration that one News Ontology relationship collapses a path the primary ontology routes through an intermediate node, recording both the path it flattened and the node it skips. It is a transformation we performed ourselves, so it is reversible from the declaration alone and is not a Divergence.
_Avoid_: Denormalized edge, direct edge, inferred relationship

**Divergence**:
A declared, unresolved gap between the News Ontology and the primary ontology: either a property the primary ontology declares that news cannot supply, or one a news write path stamps that the primary ontology does not declare. The declaration says only what is provisional and why, never how to fix it, because only an authoritative source can close it.
_Avoid_: Mismatch, schema drift, missing field, known issue

**Bill Designation**:
The chamber and number of a California bill together, normalized to the initials form — `SB 623`, `AB 1751`. It is written to a `Bill` node's `number` property by Bill Session Resolution rather than supplied by Entity Extraction, and qualifies a Bill's identity alongside its Bill Session Resolution.
_Avoid_: "bill number" used alone without a chamber

**Bill Session Resolution**:
The legislative session one Bill Designation in a Source Article resolved to, together with how it was reached: named outright by a bill link (verified), implied by the article's publication date (inferred), or settled by neither and therefore needing review. A Bill's identity is qualified by it.
_Avoid_: Session lookup, bill year, session guess

**Legislative Event Date**:
The date one Legislative Event in a Source Article resolved to, together with how it was reached: stated outright by the article (verified), stood in for by the article's publication day (inferred), or settled by neither and therefore needing review. It resolves once per Source Article, never per Article Chunk, since an event named in several chunks is one node; chunks stating different dates for it contradict each other and need review rather than resolving by order. It qualifies a Legislative Event without ever entering its identity — a wrong date in the key would conflate two events irrecoverably, whereas a name-derived key at worst fragments one event into two that a later join on date and bill can merge back.
_Avoid_: Event timestamp, occurred-on, event date guess

**Adherence Report**:
The tally of ontology items an extraction dropped from model output, bucketed by a closed set of drop categories and counted per dropped value with an example Article Chunk. It measures how closely a model followed the News Ontology; it is not an error log, because a drop is the expected handling of off-ontology output.
_Avoid_: Error log, validation errors, drop log, conformance failures

**Claim Key**:
The values that identify one relationship claim: a relationship's declared properties, and only those. Two articles asserting the same relationship at equal Claim Key values assert one claim and produce one edge; at differing values they assert two claims and produce two edges. Everything else an article said about the relationship stays in the Article Chunk the edge points back to.
_Avoid_: Edge properties, relationship payload, identifying properties, edge attributes

**Policy Area**:
A thematic policy category serving as a hub node that Bills, Props, Article Chunks, and Source Articles attach to. Its vocabulary is fixed and declared by the ontology rather than invented per article, so that two articles covering the same subject reach the same hub.
_Avoid_: Topic, tag, category, subject, theme

**Grounding Evidence**:
The Article Chunks loaded into context to support a retrieval answer. The graph is what reaches them — a query assembles a subgraph, and the Chunks attached to its nodes and edges are the evidence — rather than what supplies them: a relationship asserts existence and identity only, so the detail an answer needs lives in the Chunk the edge points back to. An answer derived from graph structure alone still carries the Chunks behind each element it counted.
_Avoid_: Context, retrieved documents, source text, supporting chunks
**Evaluation Gold Set**:
Every human-labeled example for one component operation, authored as one YAML file under `evals/gold/`. The file is the Gold Set; there is no database copy, no construction factory, and no immutable revision beyond the commit the file is read at. Revising it is editing the file and committing; reviewing a revision is reading the diff. Reading it validates every case against the task's own Pydantic types, so a mislabeled field is caught at read time rather than at run time.
_Avoid_: Test fixtures, benchmark data, model labels, dataset

**Evaluation Case**:
One authored example in a Gold Set, carrying a hand-written `id`, a description, a task input, an optional expected output, and an authored Evaluation Split. The `id` is stable across revisions of the file and is what makes a report comparable to an earlier report, so it is authored rather than derived — regenerating the file cannot silently renumber the population.
_Avoid_: Test case, sample, fixture, gold-set row

**Evaluation Split**:
Exactly one role the author assigns to each Evaluation Case: `training` supplies material for tuning agent behaviour; `calibration` reserves cases from the agent-tuning loop so judge behaviour can be observed without those cases feeding agent iteration; `held-out` reserves evidence for confirming that tuned behaviour generalizes. A case cannot participate in a tuning loop and the held-out evidence set at the same time. The split is a written field, and an imbalanced population is rebalanced by editing the file.
_Avoid_: Dataset partition, fold, case label, hashed assignment

**Evaluation Suite**:
The evaluators run against one Gold Set: the `pydantic_evals` case evaluators every case is scored by, and the report evaluators applied to the aggregate. A suite is assembled in the code that runs the task, not declared as a stored definition.
_Avoid_: Test suite, evaluator registry, suite definition

**Evaluation Rubric**:
The written criteria an LLM-judge evaluator applies to one case. It lives with the evaluator that sends it, and changing it changes the evaluator, which the commit records.
_Avoid_: Prompt, grading scale, judge config

**Evaluation Run**:
One execution of a Gold Set against one task and one model, producing one JSON report file under `evals/reports/<task>/`. The report records the commit the run executed at, whether the worktree was dirty, the model, the Gold Set path, and the split. A run whose report is not committed did not happen as far as the repository is concerned. Comparing two runs is a diff of two report files; there is no run identity, no resumption, and no finalization — an interrupted run is re-run.
_Avoid_: Experiment, job, trial, evaluation record
