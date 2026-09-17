# 02 — Retrieval execution and evidence contracts

Labels: ready-for-agent

## Parent

[Graph-Prioritized Retrieval](../PRD.md)

## What to build

Define the typed boundaries shared by retrieval branches, fusion, Evidence
Assembly, and the Chat Agent. Retrieval accepts one approved Query Rewrite and
preserves the facts needed to distinguish what was searched, what returned
evidence, and what failed.

Adopt the final evidence, citation, coverage, and answer representations from
the Useful Graph Retrieval contract. Internal failure detail remains in
structured logs, while answer-facing data carries enough information to disclose
failed branches without exposing exceptions or model output.

## Acceptance criteria

- [ ] Retrieval accepts an approved Query Rewrite, and its input has no field
      through which the original wording can reach a retrieval branch.
- [ ] The expected branch set contains full-text and dense retrieval for every
      approved rewrite and typed structural retrieval only when `relational` is
      true.
- [ ] A branch candidate retains Article Chunk identity, branch-local rank and
      score, retrieval route, matched field, and any supporting graph claim.
- [ ] Types and validation keep branch-local scores from being interpreted as
      cross-branch comparable scores.
- [ ] Successful-empty, failed, and skipped branch outcomes remain distinct.
- [ ] The execution result records expected branches, evidence recovered by
      each branch, and failed branches without requiring a `complete` or
      `partial` summary status.
- [ ] Fused candidates can retain every contributing route, graph claim, and
      pre-fusion rank.
- [ ] The evidence package represents verified passages, Source Article
      citations, relevant Coverage Description entries, and applied context
      limits using the accepted retrieval and answer contract.
- [ ] Answer-facing failure data excludes raw exceptions, internal model output,
      and unsafe diagnostics.
- [ ] Structured logging data can identify branch, stage, failure kind, attempts
      consumed, deadline exhaustion, and a safe diagnostic message.
- [ ] Contract tests prove that an empty structural result, failed structural
      result, and structurally skipped non-relational result cannot collapse to
      the same representation.

## Blocked by

- [01 — Query Rewrite and approval](01-query-rewrite-and-approval.md).
- [Useful Graph Retrieval issue 08](../../../initiatives/useful-graph-retrieval/issues/08-retrieval-and-answer-contract.md), which supplies the final evidence, citation, coverage, and answer representations.
