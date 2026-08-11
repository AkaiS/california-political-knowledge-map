# Survey graph retrieval patterns and available tooling

Labels: wayfinder:research, completed
Parent: [Useful Graph Retrieval](../MAP.md)

## Question

What established patterns and libraries exist for retrieval over a property
graph, and which are usable inside this repository's existing stack?

Cover at least:

- Neo4j's own GraphRAG guidance and the `neo4j-graphrag-python` package: which
  retrievers it ships, what it assumes about schema, and what it leaves open.
- Reported reliability of LLM-generated Cypher against non-trivial schemas, and
  the mitigations used — schema injection, few-shot examples, query validation,
  bounded repair loops.
- How full-text, vector, and structural retrieval are combined in practice, and
  how results from different modes are fused.
- Graph-aware reranking approaches and what signal they use.
- Community detection for retrieval, including Neo4j Graph Data Science
  availability and cost.
- What Pydantic AI offers for tool-selecting retrieval agents, given it is
  already the repository's agent framework.

Findings are facts for later decisions, not a recommendation. Capture them under
`work/initiatives/useful-graph-retrieval/research/`.

## Findings

Captured in
[03-graph-retrieval-patterns-findings.md](../research/03-graph-retrieval-patterns-findings.md).
Headlines, each of which constrains a later decision:

- **The local stack is barer than assumed.** Neo4j `2026.05.0` Community with
  only `chunk_vector_index`: no full-text index, no APOC, no GDS. Hybrid
  retrieval, delegated schema introspection, and community detection each
  require something that is not installed.
- **`neo4j-graphrag` 1.18.0 is compatible** (`neo4j<7`, `pydantic<3`, py<3.15)
  and ships vector, vector+Cypher, hybrid, hybrid+Cypher, text2cypher, tools,
  and external-store retrievers. It ships **no** reranking, community
  detection, mode routing, Cypher repair loop, or citation contract.
- **LLM-generated Cypher tops out around 60% execution accuracy** for frontier
  models on CypherBench, ~30% on the Neo4j Text2Cypher-2024 benchmark. Named
  failure classes include temporal conditions and same-name entity
  deduplication — this map's redistricting-cycle and identity risks exactly.
  Mitigations in documented use: schema + domain injection, dynamic few-shot
  selection, full-text entity linking, `EXPLAIN` read-only validation, bounded
  repair loops, templated Cypher.
- **Fusion is unsettled by the tooling.** Neo4j's package offers only
  max-normalized `naive` and `linear` (`alpha`) rankers, normalizing against
  the batch max; RRF (`k=60`) is the score-scale-free standard and is not
  implemented there.
- **Graph-aware reranking has no first-party tooling.** The literature's
  signals are personalized-PageRank diffusion from seeds (HippoRAG: up to 20%
  over prior SOTA multi-hop, 10–30× cheaper than iterative retrieval),
  candidate-set topology, path features, and GNN propagation.
- **Community detection means GDS.** GDS CE runs on Neo4j Community, capped at
  4-core concurrency, version-pinned to the server; Leiden is undirected-only,
  so a directed influence graph must be projected. Microsoft GraphRAG's cost is
  in indexing and in global (map-reduce) search, not local search.
- **Pydantic AI 2.0.0 covers the agent layer**: verified `FilteredToolset` /
  `PreparedToolset` per-step tool routing, `AgentToolset` delegation,
  `ModelRetry` with per-tool retry budgets as the Cypher repair seam, typed
  `output_type` for the citation contract, and `ApprovalRequired` for
  human gating. `ToolFailed` is **not** in 2.0.0 despite current docs.
