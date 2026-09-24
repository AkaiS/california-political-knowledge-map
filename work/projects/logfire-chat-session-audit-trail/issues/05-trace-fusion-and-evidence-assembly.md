# 05 — Trace fusion and Evidence Assembly

Labels: completed

## Parent

[Logfire Chat Session Audit Trail](../PRD.md)

## What to build

Let a maintainer see which Article Chunks from each completed retrieval branch were eligible for fusion, their ordered fused result, and which Grounding Evidence passages Evidence Assembly selected or omitted. The observations explain ranking and context-budget decisions using the actual typed results, including a safe account of an assembly failure.

## Acceptance criteria

- [x] A fusion span records each branch's eligible Article Chunk count and ordered IDs, plus the ordered fused output IDs. Order carries rank without a duplicate rank field.
- [x] The recorded eligible and fused IDs agree with the actual retrieval result when branches contain duplicate IDs, return more than their candidate limits, or complete in different orders.
- [x] An Evidence Assembly span records selected IDs, omitted IDs and reasons, relevant Coverage Description, applied character and passage limits, and measured context use.
- [x] A failed or deadline-exhausted fusion or Evidence Assembly result has an explicit stage status, stable failure kind, and safe diagnostic. An Evidence Assembly failure is not represented as a Retrieval Answer.
- [x] Custom application attributes omit raw scores, candidate retrieval routes, and full passage text at this stage; the final answer observation owns the selected passage snapshot.
- [x] ASGI-level tests inspect captured Logfire spans while driving the real Chat Session and deterministic fake branches and Grounding Evidence storage. They verify selection and failure facts without testing private telemetry helper calls.

## Blocked by

- [03 — Trace retrieval branch outcomes](03-trace-retrieval-branch-outcomes.md).

## Comments

Implemented on 2026-09-24. The public seam is `POST /api/chat` through
preparation and approval, using real Chat Session, retrieval coordination,
fusion, and Evidence Assembly. Deterministic branch and Grounding Evidence
storage fakes, scripted model responses, the injected clock, and an offline
Logfire exporter use existing boundaries. No public API changed.

`chat_session.fusion` records eligibility at the existing branch-limit decision
and the ordered typed fused result. `chat_session.evidence_assembly` records
selected IDs in selection order, omitted IDs with `character_limit` or
`passage_limit` reasons, relevant coverage and monthly detail, applied limits,
and measured context use. Each span carries the shared Chat Session ID and
schema version under approval. The declared attribute policy preserves valid
Article Chunk IDs containing `session` through Logfire scrubbing.

Returned assembly failures and raised stage errors record safe diagnostics and
stable `hydration`, `validation`, `unexpected`, or `deadline_exhausted` kinds.
The existing return and exception behavior is preserved, including a distinct
Evidence Assembly failure without Chat Agent guidance. Native Logfire
exception telemetry retains operational detail; custom application attributes
contain no scores, routes, or stored passage text.

Fourteen ASGI cases cover duplicate and over-limit branch candidates, reversed
concurrent completion, both omission reasons, exact context measurement,
relevant coverage, empty evidence, failed and skipped branches, hydration
failure, conflicting evidence identity, fusion validation and arithmetic
failures, and deadline exhaustion before fusion and during assembly. No live
model, Neo4j, browser, or Logfire project was used.

Validation: 127 focused tests passed. Changed-file Ruff, formatting,
`ty 0.0.83`, and `git diff --check` passed. The single final
`uv run --no-sync pytest -q` run passed with 1,328 tests, 47 skips, and the
existing Pydantic AI sampling warning. Commands used `uv` with the writable
`/private/tmp/ca-map-uv-cache` cache; type checks used the existing cached `ty`
binary through `uv run --no-sync`.
