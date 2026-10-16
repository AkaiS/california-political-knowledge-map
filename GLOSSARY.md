# California Political Knowledge Map Glossary

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
The process of identifying specific real-world entities (political actors, organizations, public policy measures) and the semantic relationships between them from unstructured article text, one Article Chunk at a time. It is not asked for Policy Areas: those are decided for the whole article by Policy Area Classification and Topic Assignment, and a Policy Area or topic relationship arriving from the chunk extractor is dropped and counted in the Adherence Report.
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

**Stance Alignment Critic**:
An LLM agent that is shown one Article Chunk and only the `DECLARED_STANCE` relationships already extracted from it, and returns each one's alignment — `POSITIVE`, `NEGATIVE`, or `NEUTRAL` — so a stance the extractor left bare carries the direction the News Ontology says a stance entails. It judges direction only: it never adds, drops, or rewrites a claim.
_Avoid_: Stance classifier, alignment tagger, sentiment agent

**Coreference Resolution Run**:
The outcome of resolving one Source Article: the resolved text, the numbered sentences shown to the annotator, every Mention Span the model returned, and each Mention Span's outcome. It is what the Coreference Adapter returns, what a coreference failure carries, and what the Dead Letter Queue records.
_Avoid_: Resolution result, coref run, annotation run

**Story Pipeline**:
A synchronous pipeline coordinator that orchestrates the coreference resolution, Policy Area Classification, chunking, embedding generation, entity extraction, Topic Assignment, and persistence steps for a Source Article.
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

**Policy Area Adapter**:
The adapter protocol and its concrete implementation behind both article-level topic stages: Policy Area Classification over a Source Article's resolved text, and Topic Assignment over that article, its areas, and its extracted measures. Two stages, one seam, so the Story Pipeline gains one collaborator and one fake covers both.
_Avoid_: Topic adapter, classifier wrapper, two adapters

**News Ontology**:
The closed ontology of the structures a Source Article can actually produce — the labels, sub-labels, per-label properties, relationships, and Policy Area vocabulary that news prose supports. It is a subset of the primary ontology (`ontology.md`), which remains the authored whole. Not every label it holds is Entity Extraction's to produce: it derives the extracted labels and relationships by setting aside the ones a named stage decides instead, `PolicyArea` and the topic relationships among them, and that derived subset is what extraction output is checked against.
_Avoid_: Schema, extraction schema, LLM schema, ontology subset

**Shortcut Rule**:
A declaration that one News Ontology relationship collapses a path the primary ontology routes through an intermediate node, recording both the path it flattened and the node it skips. It is a transformation we performed ourselves, so it is reversible from the declaration alone and is not a Divergence.
_Avoid_: Denormalized edge, direct edge, inferred relationship

**Divergence**:
A declared, unresolved gap between the News Ontology and the primary ontology: either a property the primary ontology declares that news cannot supply, or one a news write path stamps that the primary ontology does not declare. The declaration says only what is provisional and why, never how to fix it, because only an authoritative source can close it.
_Avoid_: Mismatch, schema drift, missing field, known issue

**Bill Designation**:
The chamber and number of a California bill together, normalized to the initials form — `SB 623`, `AB 1751`. It is a `Bill` node's `name`, written by Bill Session Resolution rather than supplied by Entity Extraction, and qualifies a Bill's identity alongside its Bill Session Resolution. Where no designation could be recovered, the surface string the article used stands in as the name and the Bill is flagged for review.
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

Beside the key, an edge carries only who is asserting the claim and `needs_review`. The assertion is recorded at the level the claim was decided: a chunk-level claim lists the Article Chunks asserting it, and an article-level topic claim, decided once per article and pointing back at no chunk, lists the Source Articles instead. That list is also what lets a claim be withdrawn — reprocessing an article is a fresh verdict over the same text, so it removes itself from the claims it no longer makes, and an edge nothing asserts any longer does not survive.
_Avoid_: Edge properties, relationship payload, identifying properties, edge attributes

**Policy Area Classification**:
The Story Pipeline stage that decides, once per Source Article and over its coreference-resolved text, which Policy Areas from the closed vocabulary the article discusses. It runs between Coreference Resolution and chunking, offers the vocabulary by canonical name so an id is never a second answer, and writes the article's own topic edge. An article the vocabulary does not cover classifies to none and continues.
_Avoid_: Topic Assignment, Entity Extraction, topic classification, tagging, per-chunk classification

**Topic Assignment**:
The Story Pipeline stage that decides which of a Source Article's classified Policy Areas each measure the article names is about. It runs once per article after the extraction loop, in the position Bill Session Resolution already occupies, because extraction is what discovers the measures. Its standard is what the article states rather than what a chunk states, and an assignment naming a measure no extraction produced or an area outside the article's classified set is dropped before persistence.
_Avoid_: Policy Area Classification, Entity Extraction, topic tagging, inferred topic edge

**Policy Area**:
A thematic policy category serving as a hub node that Bills, Props, and Source Articles attach to. Its vocabulary is fixed and declared by the ontology rather than invented per article, so that two articles covering the same subject reach the same hub. Policy Area Classification writes the node, and the edge to it from a Source Article is article-level: the article discusses the area, and no Article Chunk carries an edge of its own. The relationships are named for topic and the stage that draws one from a measure is Topic Assignment, so "topic" names those and never the node.
_Avoid_: Tag, category, subject, theme; "a topic" as a name for the node

**Grounding Evidence**:
The Article Chunks loaded into context to support a Retrieval Answer, reached through graph connections or other retrieval such as embedding similarity; a missing extracted relationship does not disqualify relevant source material. Answers derived from graph structure still carry the Chunks behind each element counted, and article-level topic claims reach their Chunks through the Source Article that grounds them.
_Avoid_: Context, retrieved documents, source text, supporting chunks

**Chat Agent**:
The agent responsible for assessing the person's explicit political question and guiding the reader to relevant Source Articles through a Retrieval Answer. It receives the Evidence Assembler's package directly and does not supply a standalone reporting account.
_Avoid_: Retrieval Orchestrator, Answering Agent

**Chat Session**:
The stateful interaction devoted to one explicit political question, its assessment and retrieval, and the resulting Retrieval Answer. Each search has its own results and limits; previous searches may be consulted but supply no implicit conversational context to a new question.
_Avoid_: Multi-question chat, persistent conversation

**Chat Session ID**:
An application-generated identity assigned when a Chat Session accepts its first question. It joins observations for direct question assessment, retrieval, and guidance. Historical sessions also join separate preparation and approval requests. It is distinct from individual trace IDs.
_Avoid_: Conversation ID, trace ID, approval ID

**Chat Session Audit Trail**:
The best-effort observations of a Chat Session's application stages that reached Logfire, joined by its Chat Session ID and retained for the configured project's retention period. The trail connects application decisions with operational model telemetry; an absent or expired observation establishes no terminal outcome, and a prepared Retrieval Answer establishes no browser receipt or reading.
_Avoid_: Durable audit log, complete transcript, delivery receipt

**Evidence Assembler**:
The deterministic boundary that turns ranked Grounding Evidence into the typed package returned to the Chat Agent. It retains retrieval routes and supporting graph claims, groups stored passages by Source Article, and supplies relevant coverage limits without interpreting or summarizing the evidence; stored passages may contain coreference replacements and are not necessarily original article wording.
_Avoid_: Answering Agent, Evidence Curator, context summarizer

**Relational Question**:
A question whose answer depends on one or more typed relationships among political entities or measures, including a relationship-constrained comparison, intersection, aggregate, or path. Source or passage discovery about a subject is not relational merely because retrieval follows fixed provenance links when it hydrates the result.
_Avoid_: Zero-hop question, graph question, Cypher question

**Query Rewrite Proposal**:
The legacy candidate natural-language restatement and internal route produced for a Chat Session before retrieval. Current Source Guides web and evaluation consumers preserve the original question and bypass rewriting and approval. In that legacy flow, the person sees only the restated question and either approves it as the Query Rewrite or supplies a correction for the Query Rewriter to consider in another proposal.
_Avoid_: Draft query, proposed Cypher, retrieval plan

**Query Rewrite**:
The legacy approved natural-language question from a Query Rewrite Proposal that the retrieval pipeline uses in place of the original wording. The current direct path retains this internal transport type with the original submitted wording and assessment. It makes the requested entities, relationships, scope, and result explicit in the form used by the verified query-construction cases; it does not ask separately for reporting because every retrieval returns Grounding Evidence.
_Avoid_: Retrieval plan, normalized query, Cypher query

**Retrieval Answer**:
A selection of relevant Source Articles with reading directions connecting them to the person's question and known limits on what they support. It is the result of retrieval and assessment, rather than the durable Source Guide that presents it.
_Avoid_: Expert verdict, standalone summary

**Source Guide**:
A durable, updateable organization of Source Articles and reading directions for an explicit political question. It records search limitations and outcomes and can present articles through question-specific Article Groups.
_Avoid_: Workspace, artifact

**Article Group**:
A question-specific collection of Source Articles that help the reader investigate the same aspect of the question. One article may belong to several groups; membership describes its relevance rather than assigning the article a political position.
_Avoid_: Policy Area, article stance, summary

**Declined**:
The eligibility state of a question ruled out by the system's question policy, rather than a legitimate question awaiting unavailable data. It is distinct from Deferred, empty search results, and search failure.
_Avoid_: Deferred, no results, failed search

**Deferred**:
The coverage state of a legitimate question whose required data is not yet available, expected to become answerable as coverage expands. It is distinct from a permanently Declined question and from a search that finds no matching evidence.
_Avoid_: Declined, failed search, no results

**Coverage Description**:
A succinct account of verified available material and its known coverage limits, organized by Publication or distinct public-record collection, with an authored description of what each provides. It supplies the corpus coverage context for recognizing Deferred questions; refresh operations and whether a particular search finds matching evidence are separate concerns.
_Avoid_: Search result, answer confidence

**Evaluation Data Set**:
An authored collection of Evaluation Cases for one task. It may carry human labels (Gold Set), model labels (Silver Set), or no expected outputs (Unlabeled Set). An Unlabeled Set supplies inputs for inspecting whole executions and collecting human observations; running it produces no answer-quality score. A Data Set's revision is the commit that contains it.
_Avoid_: Test fixtures, benchmark data, dataset, "the gold set" as a catch-all

**Gold Set**:
An Evaluation Data Set a person labeled, under `evals/gold/`. A score against one is agreement with a human judgement, which is the thing a component is ultimately for. The project holds exactly one — `evals/gold/relevance.yaml`, labeled by hand from its own scraped rows — and calling anything else gold overstates what a number means.
_Avoid_: Ground truth, the gold standard, reference set

**Silver Set**:
An Evaluation Data Set a model labeled against a written annotation guideline, under `evals/silver/`, with a human reviewing rather than authoring the labels. A score against one is agreement with another model's reading of that guideline: a case the annotator got wrong scores a correct answer as a miss, and a ceiling below 1.0 is expected rather than a defect. Coreference, extraction, Policy Area Classification and Topic Assignment are all measured this way, so a Silver Set score is read as a direction of travel and never compared against a Gold Set score as though the two measured the same thing.
_Avoid_: Gold set, ground truth, weak labels, pseudo-labels

**Unlabeled Set**:
An Evaluation Data Set with authored inputs and no expected outputs, under `evals/unlabeled/`. It supports error discovery from complete cases. A case may later inform a labeled set, but an Unlabeled Set run alone cannot establish accuracy or failure prevalence.
_Avoid_: Gold Set, Silver Set, answer benchmark

**Label Quality**:
Whether a Data Set has human-authored labels, model-authored labels, or no labels. Its directory and each Evaluation Report declare this value so a reader knows what a score, or the absence of one, can mean.
_Avoid_: Confidence, label source, annotation tier

**Evaluation Case**:
One authored example in a Data Set, carrying a hand-written `id`, a description, a task input, an optional expected output, and an authored Evaluation Split. The `id` is stable across revisions of the file and is what makes a report comparable to an earlier report, so it is authored rather than derived — regenerating the file cannot silently renumber the population.
_Avoid_: Test case, sample, fixture, data-set row

**Evaluation Split**:
Exactly one role the author assigns to each Evaluation Case: `training` supplies material for tuning agent behaviour; `calibration` reserves cases from the agent-tuning loop so judge behaviour can be observed without those cases feeding agent iteration; `held-out` reserves evidence for confirming that tuned behaviour generalizes. A case cannot participate in a tuning loop and the held-out evidence set at the same time. The split is a written field, and an imbalanced population is rebalanced by editing the file.
_Avoid_: Dataset partition, fold, case label, hashed assignment

**Evaluation Suite**:
The evaluators run against one Data Set, when that task has defined evaluators. An Unlabeled Set can run with no answer evaluators while its cases are reviewed. A suite is assembled in the code that runs the task, not declared as a stored definition.
_Avoid_: Test suite, evaluator registry, suite definition

**Evaluation Rubric**:
The written criteria an LLM-judge evaluator applies to one case. It lives with the evaluator that sends it, and changing it changes the evaluator, which the commit records.
_Avoid_: Prompt, grading scale, judge config

**Model Deployment**:
The concrete chat execution target an Evaluation Run or Story Pipeline invokes. The local Model Deployment is a llama.cpp-served local GGUF, while the OpenRouter Model Deployment requests a named upstream model through OpenRouter's ordered provider policy; they remain distinct even when they refer to the same upstream release, so an OpenRouter run is directional evidence about the local deployment rather than proof of equivalent behavior.
_Avoid_: Model, endpoint, provider, backend

**Model Route Summary**:
The counts of effective response-model and observed downstream-provider pairs for the requests made by one Evaluation Case. The response model follows Pydantic AI's telemetry semantics, including its fallback to the requested model, while a downstream provider that OpenRouter does not identify remains unavailable.
_Avoid_: Request Provenance, request log, provider trace, billing record

**OpenRouter Admission Gate**:
The shared control that determines when new requests for OpenRouter Model Deployments may begin after a provider rate limit, while local requests remain outside it.
_Avoid_: OpenRouter throttle, rate limiter

**OpenRouter Probe**:
The first request allowed after an OpenRouter Admission Gate's pause expires, used to establish whether waiting requests may resume.
_Avoid_: Health check, test request

**Model Reachability Check**:
The confirmation, before a command dispatches, that every local llama.cpp endpoint the command's agents depend on answers over HTTP. It is a transport question only: an endpoint that answers proves a server is accepting requests at that address, not which GGUF it loaded or that generation will succeed. A command that fails the check does no work at all, so scraping never runs ahead of the Article Validator it requires and a Story never changes status ahead of a model request that cannot be made. Chat deployment selection narrows it -- embedding stays local llama.cpp whichever chat deployment a command selects -- and `--skip-model-check` or `SKIP_MODEL_REACHABILITY_CHECK` forces a run past it.
_Avoid_: OpenRouter Probe, health check, ping, preflight

**Evaluation Run**:
One execution of a selected population from an Evaluation Data Set against one task and one Model Deployment, retaining completed outcomes, failed attempts, and unresolved cases independently of whether execution finishes. Its provenance distinguishes a full set from an explicitly requested subset; interrupted attempts remain inspectable and a new execution is a separate run.
_Avoid_: Experiment, job, trial, evaluation record

## Operational Constraints

**Local llama.cpp null-content patch**:
`utils/models.py` monkeypatches a private pydantic-ai internal,
`OpenAIChatModel._MapModelResponseContext._into_message_param`, to rewrite an
assistant message's `content: null` to `""`. The local llama.cpp
OpenAI-compatible endpoint rejects `null` there; pydantic-ai emits it for a
tool call carrying no text, which only happens on a retry turn. Without the
patch a run fails partway through with `400 invalid message content type:
<nil>`, and whether it fires at all depends on whether that particular sample
returned text alongside its tool call — so it presents as intermittent.

The patch runs at import of `utils/models.py`, which every agent reaches
through `get_chat_model` for the local deployment. OpenRouter does not use this
local workaround. It previously lived in the extraction adapter and applied
only as an import side effect, leaving coreference dependent on import order.

Being a patch against a private name, it will break silently on a pydantic-ai
upgrade rather than raising at import. The symptom is the 400 above returning.
Check this first when a previously working agent starts failing intermittently
after a dependency bump. Verified against pydantic-ai 2.0.0.
