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

## Input from the retrievable subgraph decision

[Ticket 04](04-retrievable-subgraph-now.md)'s grilling on 2026-09-08 accepted
Article Chunk embedding retrieval as a route to source material alongside graph
connections. A missing extracted relationship must not disqualify a relevant
passage found through another route. This ticket still decides mode selection,
combination, and indexes; comparative answer quality belongs to evaluation.

The [2026-09-08 live inventory](../research/04-graph-inventory-2026-09-08.md)
confirms an online 768-dimensional cosine chunk vector index covering 2,407
embedded chunks. Only the two token lookup indexes accompany it; no full-text
or property lookup indexes and no constraints were observed. The report also
records populated and empty target traversals and the missing alignment,
funding properties, and duplicate Organization identities that constrain them.
