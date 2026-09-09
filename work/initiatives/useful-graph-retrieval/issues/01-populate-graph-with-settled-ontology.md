# Update the extraction prompt to the settled ontology and populate the graph

Labels: wayfinder:task, ready-for-agent
Parent: [Useful Graph Retrieval](../MAP.md)
Specified by: [News Ontology and Graph Population](../../../projects/news-ontology-graph-population/PRD.md)

## Question

Nothing to decide. Every retrieval decision on this map is blocked until a graph
conforming to [`ontology.md`](../../../../ontology.md) exists to design and
prototype against.

Update the Extraction Prompt to the settled ontology, make the minimum write-path
changes required for the Graph Database Adapter to emit conformant nodes and
relationships, and run extraction across the Source Articles already gathered.

## Work

Specified in full by the
[News Ontology and Graph Population PRD](../../../projects/news-ontology-graph-population/PRD.md),
which supersedes the sketch below wherever they differ. Summary:

- Introduce a News Ontology — a machine-readable subset of `ontology.md` plus
  declared shortcut rules — as the single source for the Extraction Prompt's
  ontology section and for conformance of model output. `ontology.md` is not
  edited.
- Write-path changes in
  [neo4j_db.py](../../../../src/knowledge_map/adapters/neo4j_db.py): `:Article`
  becomes `:NewsArticle`, and `HAS_CHUNK` replaces `BELONGS_TO` in the
  article-to-chunk direction. `MENTIONED_IN` is retained, directed from the core
  entity to the Chunk, matching the current `ontology.md`.
- Mint deterministic project-owned primary keys. External identifiers are **not**
  recorded here: they are to be derived from structured sources rather than
  extracted from prose, and their representation is left to the modes and index
  inventory ticket.
- Resolve Bill legislative sessions from the hyperlinks already stored with each
  Story, so that recycled bill numbers do not conflate across sessions.
- Drop the existing Neo4j database — it was built against a superseded ontology —
  and re-run ingestion over the gathered Source Articles.

The broader outcome-2 migration is out of scope. Only what is needed to produce
a retrievable graph rides on this ticket.

## Blocking

- Blocks: Decide which subgraph is retrievable now and which is deferred.
- Blocks: Prototype query construction and validation against the ontology.

## Answer

### Current inventory, 2026-09-08

The [read-only graph inventory](../research/04-graph-inventory-2026-09-08.md)
records **98 CalMatters Source Articles, 2,407 Article Chunks, 3,668 nodes, and
6,061 relationships**. All ten News Ontology base labels are present, with
19 of its 20 relationship types. The report contains every label, sub-label,
and relationship count and preserves the exact queries and raw results.

- Included but empty: `IE_Committee` as an Organization sub-label, and
  `VICE_CHAIRS`. No News Ontology base label is empty.
- Excluded and absent: `District`, `ExternalIdentifier`, `LegislativeTenure`,
  and `RedistrictingCycle`; the corresponding excluded relationship types are
  listed in the inventory.
- SQLite holds 103 Stories: the 98 completed Stories exactly match the graph
  articles, and five unprocessed Stories are absent from the graph.
- Every chunk has text and a 768-dimensional embedding, and the chunk vector
  index is online. Grounding connections are present, with no dangling claim
  references found.
- All 174 stance edges lack alignment, all 12 funding edges lack amount and
  date, and 34 Organization IDs are duplicated across 70 nodes. Twenty-two
  Bills lack sessions. These limit structural answers despite source access.

This is an observation of the available corpus, not a claim of Publication
completeness or evidence that the specified rebuild ran. The surviving
adherence report has four empty maps but no run or corpus identity. The task
remains open; no data was dropped, ingested, or repaired during this inventory.

The observed graph nevertheless satisfies the factual prerequisite for issue 04's
scope decision and issue 05's read-only prototype. Those tasks can proceed with
the recorded limitations while this population task remains separate work.

### Rebuild completion requirements

Record on resolution: which ontology labels and relationship types actually
materialized and at what counts, and which remained empty — distinguishing
labels the News Ontology excludes outright from labels it includes that produced
nothing across the corpus. State the corpus size the run covered alongside the
counts; it is 73 Source Articles as of 2026-08-14, not the nine an earlier draft
of this ticket assumed. Later tickets depend on these facts.

Two of this ticket's original questions are answered by construction rather than
by a report:

- Where the Extraction Prompt and the ontology disagree is recorded by the
  generated `news-ontology.md`, not by a separate document.
- No identifier representation is used. `ExternalIdentifier` and `HAS_IDENTIFIER`
  are not materialized; the decision is deferred to
  [retrieval modes and index inventory](06-retrieval-modes-and-index-inventory.md),
  which should know that the gathered Source Articles already carry
  deterministic legislator identifiers in their stored links.
