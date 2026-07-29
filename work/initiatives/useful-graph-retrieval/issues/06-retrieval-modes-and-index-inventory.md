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
- Community-oriented retrieval, which the map's fog currently holds.

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
