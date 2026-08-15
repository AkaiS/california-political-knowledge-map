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
