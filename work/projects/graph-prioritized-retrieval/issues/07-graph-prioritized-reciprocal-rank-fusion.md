# 07 — Graph-prioritized reciprocal-rank fusion

Labels: ready-for-agent

## Parent

[Graph-Prioritized Retrieval](../PRD.md)

## What to build

Combine branch candidates through weighted reciprocal-rank fusion over their
union. Apply the numerical parameters selected by the reranking prototype so
typed structural retrieval has greater weight than either text branch without
excluding candidates found only through full-text or dense retrieval.

## Acceptance criteria

- [ ] Fusion consumes the union of branch candidates and does not require a
      candidate to appear in every branch.
- [ ] Typed structural retrieval has greater weight than either full-text or
      dense retrieval using the accepted numerical parameters.
- [ ] A candidate found through several branches accumulates each branch's
      reciprocal-rank contribution.
- [ ] A candidate absent from structural retrieval remains eligible through a
      text branch.
- [ ] Deduplication uses Article Chunk identity and retains every retrieval
      route, matched field, supporting graph claim, branch-local score, and
      pre-fusion rank.
- [ ] Fusion never compares raw scores across branches.
- [ ] Candidate deduplication does not merge graph entities or resolve identity
      ambiguity.
- [ ] Candidate limits and fusion parameters match the accepted reranking
      prototype result.
- [ ] Behavioral tests cover structural priority, text-only gap filling,
      candidates found through several routes, and rank ties.

## Blocked by

- [02 — Retrieval execution and evidence contracts](02-retrieval-execution-and-evidence-contracts.md).
- [Useful Graph Retrieval issue 09](../../../initiatives/useful-graph-retrieval/issues/09-prototype-graph-aware-reranking.md), which supplies numerical weights and candidate limits.
