# 09 — Concurrent retrieval and Chat Agent handoff

Labels: ready-for-agent

## Parent

[Graph-Prioritized Retrieval](../PRD.md)

## What to build

Connect the approved Query Rewrite, retrieval branches, fusion, and Evidence
Assembler into one bounded pipeline. Enabled branches run concurrently under
one deadline. Completed evidence survives another branch's failure, and the
assembled package returns to the same Chat Agent that received the original
question.

## Acceptance criteria

- [ ] A non-relational rewrite starts exactly the full-text and dense branches.
- [ ] A Relational Question starts exactly the full-text, dense, and typed
      structural branches.
- [ ] Every branch receives the approved Query Rewrite, never the original
      wording.
- [ ] Enabled branches start concurrently after deterministic keyword
      preparation.
- [ ] One configurable wall-clock deadline covers the retrieval run after
      approval.
- [ ] Deadline exhaustion preserves evidence from completed branches and marks
      every unfinished branch as failed.
- [ ] One branch failure never discards another branch's candidates.
- [ ] Branch candidates pass through graph-prioritized fusion and deterministic
      Evidence Assembly before the Chat Agent receives them.
- [ ] The production fusion configuration uses the numerical weights and
      candidate limits accepted by the graph-aware reranking prototype.
- [ ] Every failed branch reaches user-facing disclosure. Structural failure on
      a Relational Question is prominent, while text-branch failures remain
      visible but secondary.
- [ ] A successful empty structural traversal is presented as no matching graph
      connection in the available graph. A structural failure says the graph
      connection could not be searched.
- [ ] A Deferred coverage limit presented before approval accompanies the final
      evidence package.
- [ ] The pipeline records total model usage but applies no independent
      run-wide token ceiling.
- [ ] The Chat Agent produces one Retrieval Answer from the assembled package.
      No post-retrieval model, sufficiency loop, or automatic second retrieval
      runs.
- [ ] Fake-dependency tests cover both routes, concurrent completion, one and
      several branch failures, all branches failing, successful empty branches,
      deadline exhaustion, fusion, assembly, and final failure disclosure.

## Blocked by

- [01 — Query Rewrite and approval](01-query-rewrite-and-approval.md).
- [03 — Full-text retrieval from an approved rewrite](03-full-text-retrieval.md).
- [04 — Dense retrieval from an approved rewrite](04-dense-retrieval.md).
- [06 — Bounded multi-hop structural retrieval](06-bounded-multi-hop-structural-retrieval.md).
- [07 — Graph-prioritized reciprocal-rank fusion](07-graph-prioritized-reciprocal-rank-fusion.md).
- [08 — Deterministic Evidence Assembly](08-deterministic-evidence-assembly.md).
- [Useful Graph Retrieval issue 09](../../../initiatives/useful-graph-retrieval/issues/09-prototype-graph-aware-reranking.md), which measures the implemented branches and selects the production weights and candidate limits.
