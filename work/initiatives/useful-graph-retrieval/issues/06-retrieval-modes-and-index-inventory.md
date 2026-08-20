# Decide the retrieval modes and the index inventory they require

Labels: wayfinder:grilling, needs-triage
Parent: [Useful Graph Retrieval](../MAP.md)
Blocked by: [Decide the target question set for California political retrieval](02-target-question-set.md), [Decide which subgraph is retrievable now and which is deferred](04-retrievable-subgraph-now.md)

## Question

Which retrieval modes does the layer offer, how are their results combined, and
what indexes must exist in Neo4j to support them?

Modes to rule in or out, each justified by questions from the target set:

- Full-text search. No full-text index exists today.
- Vector similarity. Only `chunk_vector_index` exists, while the ontology also
  gives `:PolicyArea` an embedding with no index behind it.
- Structural traversal over typed relationships.

Then settle how results from multiple modes are fused into one ranked evidence
set, and whether fusion is a mode of its own or a later reranking concern.

The index half of this ticket graduates the map's identifier-representation fog.
If retrieval must resolve a node by an external key — the lookup the outcome-5
CAL-ACCESS and Open States joins will need — then the identifier store must be
indexable by source and value, which rules out a single JSON-string property and
forces parallel arrays, prefixed scalar properties, or `:Identifier` nodes.
Decide it here as an index requirement.

## Blocking

- Blocks: Decide the retrieval agent topology and orchestration.
- Blocks: Prototype graph-aware reranking.

## Comments

### Previously discussed — 2026-08-19 grilling session

- **Create a full-text index over entity `name`**, queried through
  `db.index.fulltext.queryNodes`, as the primary way a question reaches its seed
  node. Vector search over `chunk_vector_index` is the fallback when full-text
  returns nothing, and is the only path for E3, which names no entity.
- Correcting the framing in
  [the survey findings](../research/03-graph-retrieval-patterns-findings.md):
  "no full-text index" means none has been created, not that Neo4j Community
  lacks the capability. Line 152 of that document records full-text indexes as
  Lucene-backed and available. This is one `CREATE FULLTEXT INDEX` statement.
- The maintainer's retrieval design is schema-first: the graph is the entry
  point and vector retrieval is demoted to a supporting mechanism. This ticket's
  mode inventory must be read against that stance, which is being settled in its
  own session.
