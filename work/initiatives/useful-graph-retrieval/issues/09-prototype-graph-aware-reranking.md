# Prototype weights and structural signals for graph-prioritized reranking

Labels: wayfinder:prototype, needs-triage
Parent: [Useful Graph Retrieval](../MAP.md)
Blocked by: [Define the retrieval and answer contract](08-retrieval-and-answer-contract.md)
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

Select numerical weights and candidate limits, record the relevance and latency
trade-offs, and determine whether the winning signal is cheap enough to compute
per query or needs precomputation. If it needs precomputation, that is a new
ticket, not a silent addition to this one.

## Input from the retrieval modes decision

[Issue 06](06-retrieval-modes-and-index-inventory.md) closed on 2026-09-08.
Candidates come from full-text search over names, article titles, and chunk
text; Article Chunk vector search; and typed structural traversal. Combine and
deduplicate Article Chunks while retaining every retrieval route and supporting
graph claim. Name and title matches lead to candidate passages and retain their
matching field.

Issue 07 subsequently selected weighted reciprocal-rank fusion over the candidate
union and requires typed structural retrieval to receive greater weight than
either full-text or dense retrieval. This prototype owns the numerical weights,
candidate limits, and comparison of structural signals. It must still compare
the lexical and vector baselines and measure whether the chosen structural boost
improves the ranked evidence. It does not reopen structural priority or the
execution rule fixed by issue 07.

Group selected passages by Source Article for presentation. Preserve issue 04's
eligibility and coverage policy: a candidate does not need an extracted
relationship, duplicate Organization IDs do not establish distinct actors, and
missing claim properties cannot supply a structural ranking fact. External-ID
implementation and Policy Area vectors are deferred. The index requirements
are specified in issue 06; the decision did not create the new indexes.
