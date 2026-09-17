# 07 — Graph-prioritized reciprocal-rank fusion

Labels: ready-for-agent

## Parent

[Graph-Prioritized Retrieval](../PRD.md)

## What to build

Combine branch candidates through weighted reciprocal-rank fusion over their
union. Make weights, the reciprocal-rank constant, and candidate limits explicit
configuration. The implementation supplies the unweighted baseline and
structurally weighted variants that the reranking prototype will compare. A
valid production configuration requires typed structural retrieval to have
greater weight than either text branch without excluding candidates found only
through full-text or dense retrieval.

## Acceptance criteria

- [ ] Fusion consumes the union of branch candidates and does not require a
      candidate to appear in every branch.
- [ ] Branch weights, the reciprocal-rank constant, and candidate limits are
      explicit configuration rather than constants chosen by this ticket.
- [ ] Production configuration validation requires typed structural retrieval
      to have greater weight than either full-text or dense retrieval.
- [ ] The reranking prototype can run an unweighted measurement baseline and
      several weighted configurations without changing fusion code.
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
- [ ] Behavioral tests cover structural priority, text-only gap filling,
      candidates found through several routes, rank ties, configuration
      validation, and the unweighted baseline.

## Blocked by

- [02 — Retrieval execution and evidence contracts](02-retrieval-execution-and-evidence-contracts.md).
