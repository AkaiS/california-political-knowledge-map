# Prototype weights and structural signals for graph-prioritized reranking

Labels: wayfinder:prototype, ready-for-agent
Parent: [Useful Graph Retrieval](../MAP.md)
Blocked by: [Full-text retrieval](../../../projects/graph-prioritized-retrieval/issues/03-full-text-retrieval.md), [Dense retrieval](../../../projects/graph-prioritized-retrieval/issues/04-dense-retrieval.md), [Bounded multi-hop structural retrieval](../../../projects/graph-prioritized-retrieval/issues/06-bounded-multi-hop-structural-retrieval.md), [Graph-prioritized reciprocal-rank fusion](../../../projects/graph-prioritized-retrieval/issues/07-graph-prioritized-reciprocal-rank-fusion.md)
Inputs: [Accepted retrieval modes and index inventory](06-retrieval-modes-and-index-inventory.md), [Accepted retrieval topology](07-retrieval-agent-topology.md)

## Question

Which numerical weights and structural signals best implement the accepted
graph-prioritized ranking policy without burying relevant text-only evidence?

Empirical, so build it. Rank the target question set with unweighted fusion as a
measurement baseline, then compare several structurally weighted variants. The
comparison tunes the accepted policy; it does not decide whether structural
retrieval receives greater weight. Candidate signals include
entity centrality, path distance from the question's anchor entities, edge type
and its provenance strength, recency via `publish_date`, and corroboration count
across independent `NewsArticle` sources.

Corroboration deserves particular attention: an assertion supported by several
independent publications is stronger evidence than one supported by a single
article several times over, and only the graph can tell those apart.

Recommend tuned weights and candidate limits, record the relevance and latency
trade-offs, and determine whether the winning signal is cheap enough to compute
per query or needs precomputation. Any accepted change lands later as a
configuration update. If it needs precomputation, that is a new ticket, not a
silent addition to this one.

Run the comparison against the implemented full-text, dense, and bounded typed
structural branches. Use their retained pre-fusion rankings and the configurable
fusion implementation. Synthetic candidate lists may test the fusion formula,
but they cannot select production weights or establish relevance and latency
trade-offs.

This prototype is downstream measurement. It does not block implementation,
initial configuration, or the complete retrieval pipeline.

## Input from the retrieval modes decision

[Issue 06](06-retrieval-modes-and-index-inventory.md) closed on 2026-09-08.
Candidates come from full-text search over names, article titles, and chunk
text; Article Chunk vector search; and typed structural traversal. Combine and
deduplicate Article Chunks while retaining every retrieval route and supporting
graph claim. Name and title matches lead to candidate passages and retain their
matching field.

Issue 07 subsequently selected weighted reciprocal-rank fusion over the candidate
union and requires typed structural retrieval to receive greater weight than
either full-text or dense retrieval. Implementation supplies configurable
initial weights and candidate limits. This prototype compares those values and
structural signals against lexical and vector baselines, then recommends later
configuration changes if measurement supports them. It does not reopen
structural priority or the execution rule fixed by issue 07.

Group selected passages by Source Article for presentation. Preserve issue 04's
eligibility and coverage policy: a candidate does not need an extracted
relationship, duplicate Organization IDs do not establish distinct actors, and
missing claim properties cannot supply a structural ranking fact. External-ID
implementation and Policy Area vectors are deferred. The index requirements
are specified in issue 06; the decision did not create the new indexes.
