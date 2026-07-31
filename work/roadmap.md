# Roadmap

## Product outcome

Make it easier to investigate California politics by mapping politicians,
organizations, campaigns, bills, committees, public statements, funding, and
reporting into a queryable knowledge graph.

The intended experience is a question-answering and discovery layer over public
political information. Answers should expose the relationships that support
them and direct readers to the original reporting and public records.

## Product principles

- Preserve provenance from every graph assertion to its Source Article or
  public record.
- Treat the graph as a discovery layer, not a substitute for original
  reporting.
- Respect robots.txt, Publication Politeness Policies, attribution, and
  publisher traffic.
- Prefer typed contracts and explicit failure states at boundaries.
- Separate deterministic software tests from model-quality evaluations.
- Do not publish a partially extracted Source Article as if it were complete.

## Outcome sequence

### 1. Dependable source ingestion

Acquire news articles and public records repeatably, retain the evidence needed
to diagnose failures, and distinguish article-scoped failures from
system-scoped failures.

Existing project areas:

- [Scraping Pipeline](projects/scraping-pipeline/PRD.md)
- [Pipeline Stage Ownership](projects/pipeline-stage-ownership/PRD.md)
- [Flexible Category Filtering](projects/flexible-category-filtering/PRD.md)
- [Relevance Classification](projects/relevance-classification/PRD.md)
- [Batch Ingestion Orchestration](projects/batch-ingestion-orchestration/PRD.md)

### 2. Trustworthy graph creation

Transform complete Source Articles into validated Article Chunks, entities, and
relationships; preserve provenance; and write to Neo4j only when the complete
article result satisfies its contracts.

Existing project areas:

- [Article Chunking and Coreference Resolution](projects/article-chunking-coreference/PRD.md)
- [Coreference Reliability](projects/coreference-reliability/PRD.md)
- [Story Pipeline Coordinator](projects/story-pipeline-coordinator/PRD.md)
- [Influence Graph Playground](projects/influence-graph-playground/PRD.md)

Open product questions include ontology revision, multi-label entity
persistence, complete-before-write semantics, and Entity Resolution.

### 3. Measurable model quality

Evaluate every model-backed component against versioned Evaluation Gold Sets,
retain exact execution evidence, and distinguish workflow completion from model
quality and release policy.

The [Model Evaluation initiative](initiatives/model-evaluation/MAP.md) maps this
area. Its supporting projects include:

- [Shared Evaluation Contract](projects/shared-evaluation-contract/PRD.md)
- [Evaluation Contract Hardening](projects/evaluation-contract-hardening/PRD.md)
- [Case Evaluation Requirements](projects/case-evaluation-requirements/PRD.md)
- [Structured Metric Observation Materialization](projects/structured-metric-observation-materialization/PRD.md)
- [Renewable Evaluation Finalization Authority](projects/renewable-evaluation-finalization-authority/PRD.md)

### 4. Useful graph retrieval

Support entity-, edge-, neighborhood-, and community-oriented retrieval, then
measure whether answers are relevant, well-supported, and appropriately
restricted.

Expected work includes:

- A simple graph query and chat interface.
- Full-text, vector, and structural retrieval.
- Query construction and validation.
- Graph-aware reranking.
- Citation and evidence presentation.

The [Useful Graph Retrieval initiative](initiatives/useful-graph-retrieval/MAP.md)
maps this area. It designs retrieval against the settled graph ontology, targets
a developer-first consumer with a citation-bearing contract that a later chat UI
can render unchanged, and produces the retrieval and answering contract that the
Model Evaluation initiative is waiting on.

### 5. Broader public-data coverage

Add campaign-finance and legislative data after the news ingestion, graph
contracts, and evaluation seams are dependable.

Candidate sources from the original notes:

- California Civic Data / CAL-ACCESS for campaign finance.
- Open States for legislative data.
- Additional California news Publications.

## Later considerations

- Entity Resolution and graph denoising.
- Community detection and influence ranking.
- District history and overlap across redistricting.
- Hosted Neo4j and deployment pipelines.
- A user-facing dashboard for evaluations and graph exploration.

## Source

This roadmap synthesizes the verbatim imported
[Knowledge Graph vision](archive/imports/knowledge-graph-vision.md), the
[Project Notes audit](archive/imports/project-notes-2026-07-09.md), current
PRDs, the Model Evaluation wayfinder map, and repository ADRs.

