# 06 — Bounded multi-hop structural retrieval

Labels: ready-for-agent

## Parent

[Graph-Prioritized Retrieval](../PRD.md)

## What to build

Extend typed structural retrieval across the accepted relational target set.
Questions may traverse at most three question-semantic relationships. Each
model-backed construction stage gets its initial response and no more than two
corrections driven by specific deterministic feedback.

## Acceptance criteria

- [ ] Typed structural retrieval supports valid two-hop and three-hop questions
      from the verified construction cases.
- [ ] Question-semantic traversal cannot exceed three relationships.
- [ ] Fixed provenance, Source Article lookup, and Grounding Evidence hydration
      paths do not consume the semantic hop budget.
- [ ] Each model-backed construction stage receives one initial attempt and at
      most two correction attempts.
- [ ] Corrections receive the specific deterministic failure that rejected the
      preceding response.
- [ ] Questions with several Bill-name slots use an explicit multi-value
      assignment contract and never bind one Bill Designation to every slot.
- [ ] Exhausted schema filtering, selection and wiring, binding, validation,
      and hop bounds remain distinct structural failures.
- [ ] A successful three-hop search with no candidates remains a successful
      empty result rather than a construction failure.
- [ ] Controlled-graph tests cover two-hop and three-hop retrieval, correction
      success, correction exhaustion, the hop ceiling, multi-Bill binding, and
      provenance hydration beyond the semantic hop count.
- [ ] The 25 verified construction cases remain runnable as development checks
      and are not described as a held-out Gold Set.

## Blocked by

- [05 — Typed structural retrieval to Grounding Evidence](05-typed-structural-retrieval.md).
