# 03 — Record retrieval candidates and fusion

Labels: completed

## Parent

[Chat Session Audit Trail](../PRD.md)

## What to build

Make the candidate path inspectable from approved Query Rewrite through concurrent retrieval branches and fusion. Each branch records its own result and returned candidate count. Fusion records the count and ordered Article Chunk IDs from each branch that were eligible for fusion, then its ordered fused output IDs. A maintainer can compare returned counts with branch limits and see whether an expected Article Chunk ID was eligible or present after fusion. When a branch returned more than its limit, the audit cannot distinguish an ID absent from search from one cut by that limit.

## Acceptance criteria

- [x] Full-text, dense, and structural branch records share the Chat Session audit ID but have independent stage IDs and actual start and end times. No completion-order number is assigned to parallel branches.
- [x] Branch records include result or safe failure, returned candidate count, observed index identity and state when checked, and full-text search terms where applicable.
- [x] Fusion records the eligible ID count and ordered eligible IDs for each branch and the ordered fused output IDs. ID order carries rank; the audit does not duplicate rank in another field.
- [x] The audit does not copy every returned candidate, raw branch scores, per-candidate retrieval routes, or embedding vectors.
- [x] A failed branch remains distinguishable from a successful branch with zero candidates. Completed sibling branch results remain visible.
- [x] ASGI-level tests use real Chat Session coordination, fake retrievers, and a temporary audit database to exercise concurrent completion, duplicate candidate IDs, limits, empty results, and branch failure. Assert the saved IDs and counts agree with the retrieval result without requiring a particular completion order.

## Blocked by

- [01 — Open and inspect a Chat Session Audit Trail](01-open-and-inspect-a-chat-session-audit-trail.md).
