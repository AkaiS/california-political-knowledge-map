# Update the extraction prompt to the settled ontology and populate the graph

Labels: wayfinder:task, ready-for-human
Parent: [Useful Graph Retrieval](../MAP.md)

## Question

Nothing to decide. Every retrieval decision on this map is blocked until a graph
conforming to [`ontology.md`](../../../../ontology.md) exists to design and
prototype against.

Update the Extraction Prompt to the settled ontology, make the minimum write-path
changes required for the Graph Database Adapter to emit conformant nodes and
relationships, and run extraction across the Source Articles already gathered.

## Work

- Rewrite the Extraction Prompt to target the ontology's closed label set and
  sub-label convention rather than freely invented labels.
- Minimum write-path changes in
  [neo4j_db.py](../../../../src/knowledge_map/adapters/neo4j_db.py): `:Article`
  becomes `:NewsArticle`, `MENTIONED_IN` becomes `MENTIONS`, and `HAS_CHUNK`
  replaces `BELONGS_TO` in the article-to-chunk direction.
- Mint project-owned primary keys and record external identifiers as
  source/value pairs. The representation may be provisional; the map's fog
  carries the indexed form, which the modes and index inventory settles.
- Run extraction over the gathered Source Articles.

The broader outcome-2 migration is out of scope. Only what is needed to produce
a retrievable graph rides on this ticket.

## Blocking

- Blocks: Decide which subgraph is retrievable now and which is deferred.
- Blocks: Prototype query construction and validation against the ontology.

## Answer

Record on resolution: which ontology labels and relationship types actually
materialized and at what counts, which remained empty, where the Extraction
Prompt and ontology disagreed, and the identifier representation used. Later
tickets depend on these facts.
