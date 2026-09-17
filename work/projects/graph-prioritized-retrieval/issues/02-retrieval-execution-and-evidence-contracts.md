# 02 — Retrieval execution and evidence contracts

Labels: completed

## Parent

[Graph-Prioritized Retrieval](../PRD.md)

## What to build

Define the typed boundaries shared by retrieval branches, fusion, Evidence
Assembly, and the Chat Agent. Retrieval accepts one approved Query Rewrite and
preserves the facts needed to distinguish what was searched, what returned
evidence, and what failed.

Turn the contract semantics already settled by the retrievable-scope, retrieval-
mode, and topology decisions into concrete Pydantic types. This is the remaining
implementation work for Useful Graph Retrieval issue 08, not a dependency on
later wayfinder work. Internal failure detail remains in structured logs, while
answer-facing data carries enough information to disclose failed branches
without exposing exceptions or model output.

## Acceptance criteria

- [x] Retrieval accepts an approved Query Rewrite, and its input has no field
      through which the original wording can reach a retrieval branch.
- [x] The expected branch set contains full-text and dense retrieval for every
      approved rewrite and typed structural retrieval only when `relational` is
      true.
- [x] A branch candidate retains Article Chunk identity, branch-local rank and
      score, retrieval route, matched field, and any supporting graph claim.
- [x] Types and validation keep branch-local scores from being interpreted as
      cross-branch comparable scores.
- [x] Successful-empty, failed, and skipped branch outcomes remain distinct.
- [x] The execution result records expected branches, evidence recovered by
      each branch, and failed branches without requiring a `complete` or
      `partial` summary status.
- [x] Fused candidates can retain every contributing route, graph claim, and
      pre-fusion rank.
- [x] The evidence package represents verified passages, Source Article
      citations, relevant Coverage Description entries, and applied context
      limits using the accepted retrieval and answer contract.
- [x] Answer-facing failure data excludes raw exceptions, internal model output,
      and unsafe diagnostics.
- [x] Structured logging data can identify branch, stage, failure kind, attempts
      consumed, deadline exhaustion, and a safe diagnostic message.
- [x] Contract tests prove that an empty structural result, failed structural
      result, and structurally skipped non-relational result cannot collapse to
      the same representation.

## Blocked by

- [01 — Query Rewrite and approval](01-query-rewrite-and-approval.md).

## Comments

2026-09-17: Before implementation, code inspection identified these public test
seams, covered by the maintainer's advance confirmation:

- `RetrievalRequest` construction and JSON validation, consuming the existing
  approved `QueryRewrite` and deriving its expected branches.
- `BranchCandidate` and `FusedCandidate` construction and serialization,
  preserving branch-local ranking, retrieval routes, and graph claims.
- `RetrievalExecutionResult` validation and serialization, including successful
  empty, failed, and skipped structural outcomes.
- `EvidencePackage` and `RetrievalAnswer` validation and serialization, carrying
  Source Article citations, original passages, coverage, context limits, and
  branch-failure disclosures.
- `RetrievalFailureLog` validation and serialization, keeping diagnostic detail
  separate from answer-facing failures.

The tests exercise these contracts directly. Retrieval adapters, fusion,
original-wording verification, and log emission remain the later tickets that
consume them.

2026-09-17: Implemented the contracts in `schemas/retrieval.py`; their use and
validation boundaries are recorded in
[retrieval contracts](../../../../docs/retrieval-contracts.md). The approved
request derives branch expectations, and execution validation requires exactly
one consistent outcome per branch. Candidate rankings retain branch ownership;
fusion contributions preserve routes and both chunk-level and article-level
graph-claim provenance. Evidence packages group original passages by cited
Source Article and carry coverage, on-demand monthly detail, applied context
limits, Deferred assessments, and all failed branches. Fixed disclosures put
structural failure first. `RetrievalFailureLog` carries operational details
separately, and `EvidenceAssemblyFailure` remains distinct from branch failure.

The 40 contract tests passed in vertical red-green slices at the recorded seams.
The focused run with question preparation passed 55 tests. The full deterministic
suite, `uv run --no-sync pytest -q`, passed 996 tests with the same two provider
warnings recorded for issue 01. `ty check` and `ruff check` passed for the changed
source and tests. Tool commands used `uv` and a writable temporary cache; the
type checker used the existing temporary tool environment.

These types represent verified wording and applied context measurements. The
assembler must perform Story-body verification and measure the actual Chat Agent
context before constructing them. The contracts do not implement retrieval,
fusion, coverage loading, or log emission; those remain with their assigned
implementation tickets. No acceptance criterion is blocked.
