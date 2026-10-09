# 01 Submit an original question and read relevant articles

Labels: enhancement, completed
Parent: [Source Guides spec](../PRD.md)

## What to build

A voter submits their complete question and immediately begins searching. The
result displays the question and an ungrouped list of relevant Source Articles
with brief reading directions and ordinary article links. This first slice
replaces the rewrite/approval interaction through the existing application and
shared execution path. Persistence and detached execution follow in later tickets.

## Acceptance criteria

- [x] Assessment and retrieval receive the submitted wording, including names,
  dates, bounds, and requested order, without a Query Rewriter or approval step.
- [x] Broad meaningful questions proceed. An unresolved referent produces a
  typed request to edit the complete question rather than a hidden rewrite.
- [x] Every included article has a defensible reason identifying which part of
  the question it helps investigate. Reasons direct reading without supplying
  the article's arguments or conclusions. Unexplained candidates are omitted.
- [x] The guide displays all articles passing that final relevance gate, in
  relevance order unless chronology was requested. It displays the complete
  question, linked article titles, and available citation dates. Article links
  open in another tab and missing metadata is omitted.
- [x] Public responses and rendered reader content expose no Article Chunk
  bodies. Selected-source references are validated and display values retain
  existing escaping and safe-link protections.
- [x] The existing Chat Agent, Evidence Assembler, retrieval branches, fusion,
  resource limits, and loopback protections remain in use. Existing Declined,
  Deferred, partial-failure, empty, and guidance-failure outcomes remain typed.
- [x] The application and shared chat-evaluation consumer use the same direct
  question and source-guidance contract. Changed prompts get new immutable
  versions; historical prompts and evaluation records remain interpretable.

## Blocked by

None. This ticket can start immediately.

## Validation

Exercise submission and rendered outcomes at the FastAPI application boundary
with deterministic injected retrieval/model behavior. Check original wording,
relevance omission, valid references, safe rendering, typed failures, and a chunk
sentinel that must never appear publicly. Adapt affected shared-consumer checks
without creating a separate Chat Session test seam. Use the existing evaluation
workflow for controlled librarian/relevance examples. Verify submission,
editing an unresolved question, reading directions, and separate-tab source
navigation in the browser. Run required checks with uv.

## Comments

Completed after independent Standards and Spec review on 2026-10-09 UTC.
[Implementation evidence](../validation/ticket-01.md) maps all seven criteria
to application checks, controlled model examples, and browser verification.
[Review evidence](../validation/ticket-01-review.md) records the sole Standards
finding, its fix, and the final checks. No Spec findings or unresolved questions
remain. The final deterministic suite passed 1,494 tests with 61 skips; all 29
Node checks passed. Source relevance remains a model judgment evaluated through
controlled examples, not a production-corpus accuracy claim.
