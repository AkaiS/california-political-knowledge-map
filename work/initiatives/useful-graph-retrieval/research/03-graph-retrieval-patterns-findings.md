# Findings: Graph retrieval patterns and available tooling

Research supporting issue [03](../issues/03-survey-graph-retrieval-patterns.md).
These are facts for later decisions, not a recommendation. Sources are
first-party documentation, package source, peer-reviewed or preprint research,
and direct inspection of this repository's running database.

## 0. What this repository actually has today

Verified against the local instance and lockfile on 2026-08-05:

| Fact | Value |
| --- | --- |
| Neo4j server | `2026.05.0`, **Community** edition (`dbms.components()`) |
| Cypher versions offered | `5` and `25` |
| Python driver | `neo4j` 6.2.0 |
| Agent framework | `pydantic-ai` 2.0.0, `pydantic` 2.13.4 |
| Indexes present | `chunk_vector_index` (VECTOR on `:Chunk(embedding)`), two LOOKUP indexes |
| APOC installed | **No** (`SHOW PROCEDURES` returns no `apoc.*`) |
| GDS installed | **No** (no `gds.*`) |
| Labels present | `Article`, `Chunk`, `PoliticalActor`, `Organization`, `PublicPolicy`, `PublicPolicyMeasure` |
| `neo4j-graphrag` dependency | Not installed |

Consequences that constrain every option below: there is **no full-text index**,
so no hybrid mode works without creating one; **no APOC**, which several
schema-introspection paths assume; and **no GDS**, which is the only supported
route to community detection inside Neo4j. The vector index is created in
[neo4j_db.py:81](../../../../src/knowledge_map/adapters/neo4j_db.py:81) with
`vector.similarity_function: 'cosine'` and dimensions from settings.

## 1. Neo4j's `neo4j-graphrag-python` package

Package `neo4j-graphrag` 1.18.0, Apache-2.0, first-party (Neo4j, Inc.).
Dependency ranges are compatible with this repo: `neo4j>=5.17.0,<7.0.0`,
`pydantic>=2.6.3,<3.0.0`, `requires-python >=3.10,<3.15`. LLM/embedder providers
are optional extras (`openai`, `anthropic`, `google-genai`, `ollama`, `cohere`,
`litellm`, …). [pyproject.toml](https://github.com/neo4j/neo4j-graphrag-python/blob/main/pyproject.toml)

### Retrievers it ships

| Retriever | What it does | What it assumes exists |
| --- | --- | --- |
| `VectorRetriever` | k-NN over a vector index; accepts query text or a precomputed vector | A vector index; an embedder if passing text |
| `VectorCypherRetriever` | Vector seed, then a caller-supplied `retrieval_query` traverses from the seed nodes | Vector index + hand-written Cypher |
| `HybridRetriever` | Searches a vector index and a full-text index, fuses the two | **Both** a vector and a full-text index |
| `HybridCypherRetriever` | Hybrid seed + caller-supplied traversal query | Both indexes + hand-written Cypher |
| `Text2CypherRetriever` | LLM writes Cypher, package executes it | Nothing indexed; a schema string or APOC |
| `ToolsRetriever` | An LLM picks among tool-wrapped retrievers and merges their results with attribution | Whatever the wrapped tools need |
| `WeaviateNeo4jRetriever`, `PineconeNeo4jRetriever`, `QdrantNeo4jRetriever` | Vector search in an external store, then join back to Neo4j nodes by an ID property | An external vector DB |

[User Guide: RAG](https://github.com/neo4j/neo4j-graphrag-python/blob/main/docs/source/user_guide_rag.rst).
All retrievers expose a uniform `search()` returning `RawSearchResult`
(records + metadata), and the package documents writing a custom retriever when
none fit.

### What it assumes about schema

- The vector/hybrid retrievers are **schema-agnostic**: they only need index
  names, an embedding property, and optionally a list of properties to return.
  They know nothing about the ontology.
- `Text2CypherRetriever` takes an optional `neo4j_schema` string. **If omitted,
  it calls `get_schema(driver)`**, which is implemented over `apoc.meta.data`,
  `apoc.schema.nodes`, and `apoc.meta.graph`
  ([schema.py](https://github.com/neo4j/neo4j-graphrag-python/blob/main/src/neo4j_graphrag/schema.py)).
  Without APOC, the schema must be supplied by the caller. The package also has
  an "enhanced schema" mode that samples property values, distributions, and
  categorical value lists into the schema string.
- Its KG-construction pipeline (`experimental`) writes `__Entity__` /
  `__KGBuilder__` marker labels, which the schema helpers then filter out. This
  repository does not use that pipeline, so those conventions do not apply.

### What it leaves open

- **No reranking of any kind.** The `retrievers/` package contains only
  `vector`, `hybrid`, `text2cypher`, `tools_retriever`, `external`, `base`.
  There is no cross-encoder, no LLM reranker, no graph-structural rerank.
- **No community detection, no community summarization, no global/corpus-level
  search.** Nothing equivalent to Microsoft GraphRAG's map-reduce.
- **No query planning or mode routing** beyond `ToolsRetriever`'s single
  LLM tool-selection step.
- **No repair loop for generated Cypher** (see §2).
- **No citation/evidence contract.** `RawSearchResult.metadata` is free-form;
  provenance back to a Source Article is the caller's job.
- **No caching or materialization layer.**
- Graph traversal in the `*Cypher` retrievers is a **hand-written string**; the
  package does not generate or validate it against the ontology.

## 2. Reliability of LLM-generated Cypher, and the mitigations used

### Reported reliability

- **CypherBench** (11 property graphs derived from Wikidata, 7.8M entities,
  8,817 train / 2,488 test questions across 12 graph-matching patterns, with
  *politics* as one of the domains) reports execution accuracy of **61.58%
  (Claude 3.5 Sonnet)**, **60.18% (GPT-4o)**, 41.87% (Qwen2.5-72B), 38.84%
  (Llama 3.1-70B), 18.82% (Llama 3.1-8B). Failure modes named: reversed
  relationship direction, entity-linking failures (surface name ≠ stored value),
  schema-valid but intent-mismatched patterns, schema violations, incorrect
  deduplication of distinct same-named entities, and **time-sensitive
  conditions**. [arXiv:2412.18702](https://arxiv.org/abs/2412.18702)
- **Neo4j Text2Cypher (2024)** consolidated 44,387 instances from 25 public
  datasets. On execution-based evaluation the best models (GPT-4o and a
  fine-tuned `tomasonjo_text2cypher`) reached roughly a **30% match ratio**;
  the paper concludes LLMs "often struggle to capture complex nuances, resulting
  in incomplete or incorrect outputs" and that fine-tuning on domain data beat
  direct LLM use. [arXiv:2412.10064](https://arxiv.org/abs/2412.10064),
  [benchmark write-up](https://medium.com/neo4j/benchmarking-using-the-neo4j-text2cypher-2024-dataset-d77be96ab65a)
- Neo4j's own pattern catalog calls text2cypher "the most flexible, but also the
  most unreliable" pattern relative to template-based Cypher, and states it is
  not 100% reliable, struggling specifically with relationship direction, recent
  syntax, and unknown attribute types.
  [graphrag.com/reference/graphrag/text2cypher](https://graphrag.com/reference/graphrag/text2cypher/)

Two temporal and identity failure modes named in the literature — time-sensitive
conditions and same-name deduplication — map directly onto this initiative's
open questions about `RedistrictingCycle`-scoped `District` identity and
external-identifier reconciliation.

### Mitigations in documented use

1. **Schema injection.** Serialize node labels, properties with types, and
   relationship patterns into the prompt. The "enhanced schema" variant adds
   samples, value distributions, and categorical value enumerations so the model
   can translate surface forms into stored values.
2. **Domain description alongside the schema** — graphrag.com states the LLM
   should get the schema *together with a description of the domain*.
3. **Dynamic few-shot selection.** Store question→Cypher pairs with question
   embeddings; retrieve the nearest examples at generation time and inject them.
   Static example lists are the degenerate case (`examples=[...]` in
   `Text2CypherRetriever`).
4. **Full-text lookup for entity linking**, to resolve aliased names before or
   during query construction — a direct mitigation for the entity-linking
   failure class.
5. **Read-only enforcement and syntax check.** `Text2CypherRetriever` runs
   `EXPLAIN <query>` under `RoutingControl.READ` and **refuses execution unless
   `summary.query_type == "r"`**, raising `Text2CypherRetrievalError` for a
   mutating query and again on `CypherSyntaxError`.
   [text2cypher.py](https://github.com/neo4j/neo4j-graphrag-python/blob/main/src/neo4j_graphrag/retrievers/text2cypher.py)
6. **Bounded repair loop.** graphrag.com: on error, resend the question, schema,
   and error to the LLM. **The Neo4j package does not implement this** — it is a
   single shot that raises. A repair loop is caller-built.
7. **Human in the loop** where error tolerance is low.
8. **Fine-tuning** on a curated text-to-Cypher corpus (the Neo4j 2024 dataset's
   stated purpose).
9. **Template/parameterized Cypher** as the reliability-first alternative: the
   LLM fills parameters into vetted query shapes rather than writing Cypher.

## 3. Combining full-text, vector, and structural retrieval

### The primitives Neo4j provides

- **Full-text indexes** are Apache Lucene. Default analyzer
  `standard-no-stop-words`; per-index `fulltext.analyzer` (e.g. `english`, which
  applies stemming and a stop-word list); queried with
  `db.index.fulltext.queryNodes(name, query)` yielding `node, score`, always in
  descending score order. Scores are Lucene relevance scores, unbounded and not
  comparable across queries.
  [full-text-indexes.adoc](https://github.com/neo4j/docs-cypher/blob/dev/modules/ROOT/pages/indexes/semantic-indexes/full-text-indexes.adoc)
- **Vector indexes** are also Lucene, implemented as HNSW approximate k-NN.
  Config: `vector.dimensions`, `vector.similarity_function` (`cosine` preferred
  for text embeddings). As of Neo4j 2025.10 there is a native `VECTOR` property
  type, and a `SEARCH ... WHERE` clause enabling vector search *with filters* —
  newer than the `db.index.vector.queryNodes` procedure and available on the
  2026.05 server this repo runs.
  [vector-indexes.adoc](https://github.com/neo4j/docs-cypher/blob/dev/modules/ROOT/pages/indexes/semantic-indexes/vector-indexes.adoc)

### How fusion is actually done in the Neo4j package

`HybridRetriever` issues one Cypher statement with a `UNION` of the two index
searches and two selectable rankers
([neo4j_queries.py](https://github.com/neo4j/neo4j-graphrag-python/blob/main/src/neo4j_graphrag/neo4j_queries.py)):

- **`naive`** (default): each side's scores are divided by that side's max score
  in the result set, then `max(score)` per node wins.
- **`linear`**: same max-normalization, then
  `final = alpha * vector_norm + (1 - alpha) * fulltext_norm`, summed per node;
  a node missing from one side contributes 0 there. `alpha` is **required** for
  this ranker and must be in [0,1] — there is no default weighting.
- `effective_search_ratio: int = 1` multiplies `top_k` to widen the vector
  candidate pool before fusion.

Note both rankers normalize by the **max score within the returned set**, so
scores are relative to the batch, not calibrated across queries.

### Reciprocal Rank Fusion — the standard alternative

RRF ignores scores and fuses by rank: `score(d) = Σ_i 1/(k + rank_i(d))`.
Cormack, Clarke & Buettcher (SIGIR 2009) report it consistently beats any single
input system and beats Condorcet Fuse; **k = 60** was the best average value in
their benchmarks. It is score-scale-free, which is what makes it attractive when
fusing an unbounded Lucene score with a bounded cosine similarity.
[SIGIR 2009](https://dl.acm.org/doi/10.1145/1571941.1572114)
Neo4j's package does **not** implement RRF.

### Structural retrieval in the mix

The practiced pattern is **seed then traverse**: a lexical or vector search
identifies entry nodes, and a Cypher `retrieval_query` expands from them
(`VectorCypherRetriever` / `HybridCypherRetriever`). Fusion happens on the seeds;
the traversal output is context, not a ranked list. Anything that ranks
*expanded* results is reranking (§4), not fusion.

## 4. Graph-aware reranking, and the signals used

No first-party Neo4j tooling exists for this. The research literature converges
on a small set of signals:

- **Personalized PageRank (PPR) diffusion from query-linked seed nodes.**
  HippoRAG runs PPR over an LLM-built KG to select passages; reports up to **20%
  improvement over prior SOTA RAG on multi-hop QA**, at **10–30× lower cost and
  6–13× lower latency** than iterative retrieval (IRCoT), in a single retrieval
  step. [arXiv:2405.14831](https://arxiv.org/abs/2405.14831). The mechanism —
  semantically coherent clusters mutually reinforce, isolated hits receive
  little diffusion — is the canonical structural rerank signal.
- **Graph topology over the candidate set rather than per-candidate scoring.**
  Graph-based rerankers score candidates jointly using edges between them,
  in contrast to pointwise rerankers that judge each candidate independently.
  GraphER adds offline enrichment plus an online "Graph Cohesive Smoothing"
  step and reports gains over PPR.
  [arXiv:2603.24925](https://arxiv.org/html/2603.24925v1)
- **Path-based signals**: shortest-path length to a query entity, number of
  distinct connecting paths, relationship-type relevance, and ego-graph pruning
  (LEGO-GraphRAG-style modular pipelines).
- **Learned/GNN propagation** of query-specific signal through the graph,
  modelling semantic affinity and structural connectivity together.
  [GraphRAG survey, arXiv:2501.00309](https://arxiv.org/html/2501.00309v2)
- **Conventional signals still apply** and are orthogonal: cross-encoder
  relevance, recency, and source authority. For this domain, publication date
  and source article count per claim are available structural-adjacent signals.

Note that PPR-style reranking needs a graph algorithm runtime — either GDS
(§5) or an in-process implementation over a subgraph pulled into Python.

## 5. Community detection: availability and cost

### Inside Neo4j

Community detection requires the **Graph Data Science library**; it is a
separate plugin, not core Cypher, and **is not installed** on this repo's
server.

- **Editions.** GDS ships one artifact that operates as Community Edition by
  default; Enterprise features unlock with a license key file configured via
  `gds.enterprise.license_file`. The **only license-gated resource limit that
  matters here is concurrency: GDS CE caps maximum concurrency at 4 cores**;
  GDS EE is unlimited. The docs explicitly state this limit follows the *GDS*
  license, not the Neo4j database edition — so GDS CE runs on this Neo4j
  Community server.
  [System-requirements.adoc](https://github.com/neo4j/graph-data-science/blob/master/doc/modules/ROOT/pages/installation/System-requirements.adoc),
  [installation-enterprise-edition.adoc](https://github.com/neo4j/graph-data-science/blob/master/doc/modules/ROOT/pages/installation/installation-enterprise-edition.adoc)
- **Licensing of the code**: GPLv3, superseded by a commercial agreement if one
  exists. EE list pricing is not published; third-party aggregators quote
  five-figure annual ranges, which should be treated as unverified.
- **Leiden is available** and is a hierarchical modularity-maximizing algorithm
  built to fix Louvain's poorly-connected-community defect. Its algorithm traits
  are `undirected` and **not directed** — a directed political-influence graph
  must be projected to undirected before Leiden will run.
  [leiden.adoc](https://github.com/neo4j/graph-data-science/blob/master/doc/modules/ROOT/pages/algorithms/leiden.adoc)
- **Version compatibility** is tight: GDS pins to Neo4j versions
  (Neo4j `2026.02.0` → GDS `2.27`, `2026.01.4` → `2.26`, `5.26` → `2.13`), and
  recent GDS releases adopt date versioning matching the server
  (`2026.07.0`, `2026.06.0`, `2026.05.0` published).
  [supported-neo4j-versions.adoc](https://github.com/neo4j/graph-data-science/blob/master/doc/modules/ROOT/pages/installation/supported-neo4j-versions.adoc),
  [releases](https://github.com/neo4j/graph-data-science/releases)
- Operationally, GDS runs on **projected in-memory graphs** (graph catalog),
  not directly on the store; results are `stream`ed, `mutate`d in the projection,
  or `write`-back as node properties. Community assignment is therefore a
  materialization step with an invalidation question after re-ingestion.
- Managed alternative: **Aura Graph Analytics** gives EE features without a
  license or install; **AuraDS** is managed GDS EE.

### Community detection *for retrieval*

Microsoft GraphRAG is the reference design: hierarchical Leiden partitions the
entity graph recursively (level 0 = broad root communities, deeper levels = more
specific), each community gets an LLM-generated summary at index time, and
**global search** map-reduces over community summaries to answer corpus-wide
questions, while **local search** traverses entity neighborhoods for specific
lookups; DRIFT combines them. Reported result: substantial gains over
conventional RAG in *comprehensiveness and diversity* on global sensemaking
questions over ~1M-token corpora.
[arXiv:2404.16130](https://arxiv.org/abs/2404.16130),
[community detection docs](https://microsoft.github.io/graphrag/index/default_dataflow/)

Cost profile: the expense is **indexing**, not querying — an LLM call per chunk
for extraction plus a summary per community. Query cost is asymmetric: local
search is cheap; global search scales with the number of communities and
therefore with corpus size. Microsoft Research's own follow-ups target exactly
this — *dynamic community selection* (rate community relevance with a cheap
model before summarizing) and *LazyGraphRAG*, which defers summarization to
query time.
[dynamic community selection](https://www.microsoft.com/en-us/research/blog/graphrag-improving-global-search-via-dynamic-community-selection/),
[LazyGraphRAG](https://www.microsoft.com/en-us/research/blog/lazygraphrag-setting-a-new-standard-for-quality-and-cost/)

## 6. What Pydantic AI offers for tool-selecting retrieval agents

Verified against the installed `pydantic-ai` **2.0.0**, not just the docs.

### Present and usable in 2.0.0

- **Function tools** registered by decorator or constructor argument, with
  schemas derived from signature + docstring, and `RunContext` dependency
  injection for the driver/embedder.
- **Toolsets** as first-class composable units. Confirmed importable from
  `pydantic_ai.toolsets`: `FunctionToolset`, `CombinedToolset`,
  `FilteredToolset`, `PreparedToolset`, `PrefixedToolset`, `RenamedToolset`,
  `ApprovalRequiredToolset`, `DeferredLoadingToolset`, `ExternalToolset`,
  `IncludeReturnSchemasToolset`, `SetMetadataToolset`, `WrapperToolset`,
  `AgentToolset`, `AbstractToolset`.
  - `FilteredToolset` / `PreparedToolset` decide **per step** which tools the
    model may see, from `RunContext` and the `ToolDefinition` — the mechanism for
    routing retrieval modes without a separate router model.
  - `AgentToolset` exposes an agent as a tool (agent delegation), which is how a
    Generator/Critic pair or a specialist sub-retriever would be composed.
- **`ModelRetry`**, confirmed present. Raising it from a tool, an args
  validator, an output function, or an output validator produces a
  `RetryPromptPart` sent back to the model with the exception message — this is
  the bounded repair loop for generated Cypher, with the error text as the
  repair signal. Limits are layered: per-tool (`@agent.tool(retries=N)` /
  `Tool(max_retries=N)`), per-toolset (`FunctionToolset(max_retries=N)`),
  then agent-wide; exhaustion raises `UnexpectedModelBehavior`. Retry counters
  are **per tool**, not a shared run budget.
- **Structured `output_type`** with output functions and output validators, so
  a typed answer contract carrying citations and evidence is enforced by the
  framework rather than by prompt discipline.
- **`ApprovalRequired` / `CallDeferred` / `DeferredToolRequests`** for
  human-in-the-loop gating of specific tool calls — the hook a "confirm this
  generated Cypher" step would use.
- The framework's own **`sql_gen` example** is the closest shipped analogue:
  dynamic system prompt carrying the schema, structured output, and validation
  by running the query as `EXPLAIN` against the database, with failures fed back
  as retries. **`rag` example** is a plain vector-search tool over pgvector.
  [sql-gen](https://github.com/pydantic/pydantic-ai/blob/main/docs/examples/sql-gen.md),
  [rag](https://github.com/pydantic/pydantic-ai/blob/main/docs/examples/rag.md)

### Documented on `main` but **absent in 2.0.0** — verify before designing on

- **`ToolFailed`** is not importable from `pydantic_ai` in 2.0.0. The
  terminal-failure-vs-retry distinction described in current docs is unavailable
  without an upgrade; today a non-retryable failure must be modelled as a normal
  tool return value.
- Other `main`-only features described in current docs (agent-wide
  `retries={'tools': N}` dict form, per-run retry overrides, tool timeouts,
  `ToolSearch`) should each be checked against 2.0.0 before being assumed.

### What Pydantic AI does not provide

No retrieval primitives, no Neo4j integration, no reranking, no fusion, no
index management. It provides the agent loop, tool exposure/filtering, typed
output, and the retry seam; everything graph-specific is repository code.
`neo4j-graphrag`'s `Tool` abstraction (`neo4j_graphrag/tool.py`) is its own
JSON-schema tool model and is not a Pydantic AI toolset, so wiring the two
together means wrapping retrievers as plain Pydantic AI function tools rather
than reusing `ToolsRetriever`.

## 7. Facts that bear directly on this map's open questions

- Hybrid retrieval is **blocked on creating a full-text index**; none exists.
  Whether external identifiers are searchable by key is a full-text/index design
  question, not just a storage-shape question.
- **APOC is absent**, so any schema-injection path must be repository-owned
  (serialized from `ontology.md` or from `SHOW INDEXES`/`CALL db.schema`), not
  delegated to `neo4j-graphrag`'s `get_schema`.
- **GDS is absent** and community detection has no in-database alternative;
  the community orientation therefore costs a plugin install (GDS CE, 4-core
  concurrency cap, version-pinned to the 2026.05 server) plus a projection and
  materialization step, or an out-of-database implementation.
- Two of the highest-frequency text2cypher failure classes in the literature —
  temporal conditions and same-name entity deduplication — are exactly the
  redistricting-cycle and entity-identity risks this map already flags.
- A bounded Cypher repair loop is **not** available off the shelf from
  `neo4j-graphrag` (single shot, raises) but **is** available from Pydantic AI
  (`ModelRetry` with per-tool limits), and `Text2CypherRetriever`'s
  `EXPLAIN` + `query_type == "r"` check is a reusable read-only guard
  independent of that package.
