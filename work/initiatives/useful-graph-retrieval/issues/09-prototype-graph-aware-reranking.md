# Prototype graph-aware reranking

Labels: wayfinder:prototype, needs-triage
Parent: [Useful Graph Retrieval](../MAP.md)
Blocked by: [Decide the retrieval modes and the index inventory they require](06-retrieval-modes-and-index-inventory.md), [Define the retrieval and answer contract](08-retrieval-and-answer-contract.md)

## Question

Does graph structure improve ranking over lexical and vector baselines, and which
structural signal does the work?

Empirical, so build it. Rank the target question set with the chosen modes alone,
then with structural signal layered on, and compare. Candidate signals include
entity centrality, path distance from the question's anchor entities, edge type
and its provenance strength, recency via `publish_date`, and corroboration count
across independent `NewsArticle` sources.

Corroboration deserves particular attention: an assertion supported by several
independent publications is stronger evidence than one supported by a single
article several times over, and only the graph can tell those apart.

Record whether reranking justifies its latency, and whether the winning signal
is cheap enough to compute per query or needs precomputation. If it needs
precomputation, that is a new ticket, not a silent addition to this one.
