# Prototype graph-aware reranking

Labels: wayfinder:prototype, needs-triage
Parent: [Useful Graph Retrieval](../MAP.md)
Blocked by: [Define the retrieval and answer contract](08-retrieval-and-answer-contract.md)
Inputs: [Accepted retrieval modes and index inventory](06-retrieval-modes-and-index-inventory.md)

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

## Input from the retrieval modes decision

[Issue 06](06-retrieval-modes-and-index-inventory.md) closed on 2026-09-08.
Candidates come from full-text search over names, article titles, and chunk
text; Article Chunk vector search; and typed structural traversal. Combine and
deduplicate Article Chunks while retaining every retrieval route and supporting
graph claim. Name and title matches lead to candidate passages and retain their
matching field.

This prototype owns shared ranking of those candidates as well as the comparison
of structural signals. Issue 06 selects no fusion formula, mode weights, or
structural preference; combination itself is not another retrieval mode. Compare
the lexical and vector baselines before deciding how structural evidence should
affect the combined ranking. Mode selection and execution remain issue 07's work.

Group selected passages by Source Article for presentation. Preserve issue 04's
eligibility and coverage policy: a candidate does not need an extracted
relationship, duplicate Organization IDs do not establish distinct actors, and
missing claim properties cannot supply a structural ranking fact. External-ID
implementation and Policy Area vectors are deferred. The index requirements
are specified in issue 06; the decision did not create the new indexes.
