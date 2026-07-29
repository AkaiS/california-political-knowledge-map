# Survey graph retrieval patterns and available tooling

Labels: wayfinder:research, ready-for-agent
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
