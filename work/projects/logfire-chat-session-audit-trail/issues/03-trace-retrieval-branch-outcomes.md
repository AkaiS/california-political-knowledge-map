# 03 — Trace retrieval branch outcomes

Labels: ready-for-agent

## Parent

[Logfire Chat Session Audit Trail](../PRD.md)

## What to build

After a person approves a Query Rewrite, show how full-text, dense, and structural retrieval each ran under the shared deadline. A maintainer can distinguish a successful empty branch, a branch failure, and a structural branch skipped because the question was not relational. Parallel branches have separate spans and actual timing, with no fabricated order.

## Acceptance criteria

- [ ] Each enabled retrieval branch has a span beneath approval work with the Chat Session ID, branch name, actual start and end times, result status, and returned candidate count.
- [ ] Full-text search records its prepared search terms. Retrieval records index identity and observed state when an existing lookup supplied those facts, without a new audit-only index query.
- [ ] A non-relational question emits an explicit skipped structural observation with a reason and zero candidates.
- [ ] A failed branch records a stable failure stage and kind with a safe diagnostic. Completed sibling branch results remain inspectable.
- [ ] Custom branch attributes exclude embedding vectors, raw branch scores, per-candidate routes, and a copy of every returned candidate.
- [ ] ASGI-level tests drive real Chat Session coordination with fake retrievers through concurrent completion, an empty result, a branch failure, a deadline, and a skipped branch. Captured branch results match the typed retrieval outcomes without asserting completion order.

## Blocked by

- [02 — Trace question preparation and approval](02-trace-question-preparation-and-approval.md).
