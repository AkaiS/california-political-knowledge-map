# 07 — Graph-prioritized reciprocal-rank fusion

Labels: ready-for-agent

## Parent

[Graph-Prioritized Retrieval](../PRD.md)

## What to build

Combine branch candidates through weighted reciprocal-rank fusion over their
union. Make weights, the reciprocal-rank constant, and candidate limits explicit
configuration with documented initial defaults. The initial structural weight
must exceed either text-branch weight without excluding candidates found only
through full-text or dense retrieval. Exact tuning is later measurement work and
does not block this implementation.

## Acceptance criteria

- [ ] Fusion consumes the union of branch candidates and does not require a
      candidate to appear in every branch.
- [ ] Branch weights, the reciprocal-rank constant, and candidate limits are
      explicit configuration with documented initial defaults.
- [ ] The initial and any replacement configuration requires typed structural
      retrieval to have greater weight than either full-text or dense retrieval.
- [ ] An unweighted measurement baseline and alternative weighted
      configurations can run without changing fusion code.
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
