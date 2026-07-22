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
A versioned, contract-homogeneous collection of human-labeled examples used as the authoritative expected outcomes for one component operation. It binds one exact Evaluation Task Contract, and every member implements that contract's input, expected-output, and metadata schemas.
_Avoid_: Test fixtures, benchmark data, model labels

**Evaluation Case**:
An immutable, stably identified authored example declaring zero or more distinct Evaluation Requirements, whose revisions preserve changes to its input, expected outcome, requirements, or authoritative artifacts. Evaluation Gold Set versions assign exact Evaluation Case revisions to splits without rewriting earlier membership.
_Avoid_: Test case, sample, fixture, gold-set row

**Evaluation Task Contract**:
The exact typed input, output, and metadata boundary of one component operation evaluated by an Evaluation Suite. All of the suite's Evaluation Cases implement this shared contract; heterogeneous shapes are explicit variants within its schemas rather than case-specific contracts.
_Avoid_: Case contract, test schema, suite case type

**Schema Reference**:
The exact identity, revision, and JSON-schema fingerprint of an authored Pydantic model contract. Structured Evaluation Metric Definitions own their value Schema References, while Suites expose them through a derived inventory without storing executable model types.
_Avoid_: Runtime model path, schema label, database type

**Resolved Schema Binding**:
The persistence-free runtime association between one expected Schema Reference and one allowlisted concrete Pydantic model type used to materialize a structured Evaluation Metric Observation.
_Avoid_: Schema import, untyped payload, serialized model

**Structured Metric Observation Materialization**:
The explicit reconstruction of one fetched schema-tagged structured Evaluation Metric Observation into its allowlisted evaluator-owned Pydantic model after the frozen Evaluation Suite resolves the governing Metric Definition. Scalar observations remain directly usable and are not materialized.
_Avoid_: Database fetch, dictionary cast, report blob deserialization

**Evaluation Task Binding**:
The persistence-free runtime association between an evaluated component operation and the exact Evaluation Task Contract it implements. It is the sole boundary that turns each component invocation into a validated Evaluation Task Outcome and attaches references to task-produced or failure evidence.
_Avoid_: Task callable, model function, output validator

**Evaluation Task Outcome**:
The terminal result of applying the evaluated component operation to one manifested Evaluation Case: either a typed success conforming exactly to the Evaluation Task Contract or a provider-neutral failure. An output contract violation is a task failure, not a successful outcome or evaluator failure.
_Avoid_: Task result, component result, evaluator outcome

**Evaluation Suite**:
A versioned, component-specific evaluation definition for one component operation that binds its Evaluation Task Contract to compatible Evaluation Cases, owns Configured Evaluators and Evaluation Requirement Bindings, requires at least one serialized report-evaluator configuration, and declares metric semantics. It consumes an Evaluation Gold Set but excludes provider and execution configuration.
_Avoid_: Test suite, benchmark suite, model configuration

**Configured Evaluator**:
A uniquely named, suite-local evaluator declaration containing an evaluator revision, canonical configuration, and references to its rubrics and metric semantics. Case and report evaluator declarations occupy separate typed collections but have names unique across the Evaluation Suite; every configured case evaluator is referenced by suite-wide application or at least one Evaluation Requirement Binding, though that binding may be dormant for a particular run.
_Avoid_: Evaluator instance, evaluator definition, evaluator binding

**Evaluation Requirement**:
A stable, case-owned semantic capability key from the component's Evaluation Requirement Catalog, declaring a special kind of evaluation the case requires beyond Suite-wide Case Evaluators. It does not select an evaluator implementation, configuration, rubric, model, or metric; a fundamentally different meaning receives a new key rather than revising the existing key. A Suite–Gold Set pairing is incompatible when the suite cannot bind every requirement declared by its selected cases.
_Avoid_: Evaluator preference, evaluator name, rubric reference, case scoring config

**Evaluation Requirement Catalog**:
The component-owned closed vocabulary of valid Evaluation Requirement keys and their immutable semantic descriptions. Adding a key does not revise existing authored evaluation definitions, while changing a key's meaning requires introducing a new key.
_Avoid_: Evaluator registry, suite requirements, arbitrary requirement strings

**Evaluation Requirement Binding**:
A suite-owned mapping from an Evaluation Requirement key to a non-empty set of Configured Evaluators that collectively satisfy it. Every bound evaluator is applied deterministically to each selected case declaring the requirement; bindings are not alternatives or fallbacks. A binding unused by a particular Gold Set or run selection remains dormant and creates no expected evaluator execution.
_Avoid_: Case Evaluator Binding, case override, evaluator capability

**Resolved Evaluation Plan**:
The immutable per-run assignment of Configured Evaluators to the exact manifested Evaluation Case revisions, derived and frozen before execution from Suite-wide Case Evaluators and every selected case's Evaluation Requirements and the suite's bindings. Overlapping assignments are deduplicated into one evaluator application while retaining which requirements each application satisfies; every execution path consumes this same plan.
_Avoid_: Runtime evaluator list, dataset configuration, execution report

**Evaluation Checkpoint**:
An atomic durable commit of one completed case and its task and case-evaluator evidence, or of one completed report-evaluator execution and its run-level evidence. Checkpoints preserve completed work when later evaluation or orchestration fails; Task Bindings and evaluators describe evidence without owning persistence.
_Avoid_: Save point, evaluator side effect, partial report

**Evidence Contract Version**:
The single durable semantic version governing both interpretation of persisted Evaluation Checkpoints and deterministic materialization of evaluator-visible report inputs. The installed Pydantic Evals version and the materializer implementation are not separately persisted version authorities.
_Avoid_: Materializer version, Pydantic Evals compatibility version, report schema version

**Frozen Aggregate Manifest**:
A canonical, content-addressed artifact that fixes one Evaluation Run's exact Suite, Resolved Evaluation Plan, Evaluation Task Contract, evidence-contract version, report-level provenance, and ordered terminal Evaluation Checkpoint composition by identity and content hash. It contains integrity references rather than copied authored case values or complete ReportCase payloads; the Evaluation Report is deterministically derived from the referenced immutable definitions and checkpoints.
_Avoid_: Frozen report, aggregate report blob, report snapshot

**Evaluation Ledger**:
The durable transaction boundary for imported evaluation definitions and execution evidence. It presents one cohesive persistence façade while definition, execution/checkpoint, and artifact responsibilities remain internally separated behind the same atomic boundary.
_Avoid_: Evaluation database, SQLite store, repository collection

**Evaluation Finalization**:
The resumable report-evaluation phase of an Evaluation Run after every manifested case has a terminal checkpoint and their exact ordered composition is frozen in a Frozen Aggregate Manifest. It verifies the manifest, deterministically materializes the derived Evaluation Report, executes only report evaluators lacking terminal evidence, and requests completion; the durable run record authorizes that transition only after all expected terminal evidence exists. Loss of finalization authority does not interrupt an already-started evaluator invocation, but its evidence is rejected and no further evaluator work begins; the run remains available for recovery.
_Avoid_: Run retry, report retry, evaluation resume

**Evaluation Finalization Attempt**:
One bounded effort to perform Evaluation Finalization under a single continuously held authority claim. Authority expiry irreversibly ends the attempt even when no successor has claimed the run. An attempt that loses authority discards uncheckpointed evaluator output and ends without reacquiring authority or cancelling the Evaluation Run; a new attempt may resume the run from its terminal evidence. A controlled stop begins no further evaluator or gate work, ends renewal after any in-flight evaluator returns, requests early release as best-effort cleanup, and leaves the run pending without recording an issue; unconfirmed release delays recovery only until authority expires.
_Avoid_: Evaluation Run retry, evaluator retry, lease retry

**Suite-wide Case Evaluator**:
A case evaluator configured by an Evaluation Suite and applied to every Evaluation Case selected for a run. Its application is additive with evaluators selected through Evaluation Requirement Bindings, and the Resolved Evaluation Plan applies the same Configured Evaluator at most once to a case.
_Avoid_: Default evaluator, global evaluator, universal evaluator

**Evaluation Rubric**:
A versioned, human-authored policy of criteria and assertions used by a model-based evaluator to judge outputs. Evaluation Suites reference exact Evaluation Rubric revisions so changes in judging semantics remain reproducible.
_Avoid_: Judge prompt, evaluator definition, scoring instructions

**Evaluation Run**:
One immutable case-execution attempt of an Evaluation Suite against a specific component, configuration, and Evaluation Gold Set version, retained even when incomplete or unsuccessful. Completion means every case and evaluator assignment in its Resolved Evaluation Plan has terminal evidence and its Frozen Aggregate Manifest is linked, not that every task, evaluator, metric, or release gate succeeded; incomplete case execution requires a distinct linked retry, while incomplete report evaluation may resume as Evaluation Finalization on the same run.
_Avoid_: Test run, benchmark, experiment

**Evaluation Run Issue**:
A durable, factual quality or lifecycle diagnostic attached to an Evaluation Run independently of its workflow status. An expired finalization claim replaced during recovery produces a claim-recovery issue identifying the prior attempt and its observed expiry without inferring why its authority lapsed; worker-local causes remain operational telemetry.
_Avoid_: Evaluator failure, run status reason, speculative incident diagnosis

**Release Gate**:
A side-effect-free, deterministic policy check over terminal Evaluation Run evidence and explicit gate configuration. It produces a pass or fail outcome, may be safely replayed during Evaluation Finalization recovery, and never performs the external release action that may consume its persisted outcome.
_Avoid_: Deployment hook, evaluator, approval side effect, mutable policy lookup

**Evaluation Run Configuration**:
The immutable, canonical, secret-free snapshot of shared execution settings, including bounded case concurrency, and the Validated Component Configuration used by an Evaluation Run. Its content fingerprint identifies materially equivalent configuration across runs; case concurrency defaults to one unless explicitly selected.
_Avoid_: Runtime config, environment snapshot, model settings

**Validated Component Configuration**:
The normalized, secret-free effective configuration used to construct the component under evaluation, represented by that component's validation model and recorded with the Evaluation Run.
_Avoid_: Typed extension, raw environment, component options

**Evaluation Case Manifest**:
The immutable set of exact Evaluation Case revisions selected for an Evaluation Run, together with the provenance of how they were selected. It defines the population measured by aggregate observations when a run executes all or part of an Evaluation Gold Set version.
_Avoid_: Case filter, dataset subset, selected rows

**Evaluation Case Result**:
A result envelope created for each Evaluation Case selected by an Evaluation Run, separating execution disposition, task outcome, and independent evaluator outcomes. It preserves partial evidence and distinguishes task failures from evaluator failures.
_Avoid_: Test result, row, sample output

**Case Evaluator Execution**:
One recorded application of a case evaluator to an Evaluation Case Result, including whether that invocation completed or failed and any Evaluation Metric Observations it produced.
_Avoid_: Evaluator result, case metric, generic evaluator execution

**Report Evaluator Execution**:
One recorded application of a report evaluator invoked after case evaluation against an Evaluation Run report, including whether that invocation completed or failed and any run-level Evaluation Metric Observations it produced.
_Avoid_: Run evaluator, generic evaluator execution

**Evaluation Metric Definition**:
An immutable, repository-wide authored definition of an evaluation measurement, identified by a namespaced name and evaluator revision and declaring its observation value type, comparison operation, and semantic description. A structured definition also declares the exact object-shaped value schema that every observation must satisfy; its named fields give each constituent value semantic meaning, while collections may appear only beneath those fields. The metric identity and value-schema identity are distinct contracts. Suites may reuse the exact definition across different Evaluation Task Contracts when those measurement semantics remain identical.
_Avoid_: Metric, score definition, display label

**Evaluation Metric Observation**:
A value measured under an Evaluation Metric Definition and owned by the evaluator execution that produced it. Its value must conform to the type and, for structured observations, the exact object-shaped schema declared by that definition. A Case Metric Observation derives its Evaluation Case Result through its Case Evaluator Execution, while a Run Metric Observation derives its Evaluation Run through its Report Evaluator Execution.
_Avoid_: Score, metric result, measurement row

**Evaluation Comparison Operation**:
A versioned rule for comparing baseline and candidate values of an Evaluation Metric Definition, producing a shared better, equivalent, worse, or incomparable result. It may use shared scalar ordering or evaluator-owned logic for structured values; release thresholds remain separate gate configuration.
_Avoid_: Comparison direction, threshold, release gate

**Evaluation Artifact**:
Immutable content used or produced by evaluation and identified by its content hash, kind, media type, size, retention class, and sensitivity classification. Redacted content is a distinct Evaluation Artifact rather than a replacement for its source.
_Avoid_: Artifact reference, file path, CI URL, blob

**Artifact Location**:
A replaceable location from which an Evaluation Artifact can be resolved. An Evaluation Artifact may have multiple locations without changing its identity.
_Avoid_: Artifact identity, content hash
