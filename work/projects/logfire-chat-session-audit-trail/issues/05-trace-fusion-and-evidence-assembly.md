# 05 — Trace fusion and Evidence Assembly

Labels: ready-for-agent

## Parent

[Logfire Chat Session Audit Trail](../PRD.md)

## What to build

Let a maintainer see which Article Chunks from each completed retrieval branch were eligible for fusion, their ordered fused result, and which Grounding Evidence passages Evidence Assembly selected or omitted. The observations explain ranking and context-budget decisions using the actual typed results, including a safe account of an assembly failure.

## Acceptance criteria

- [ ] A fusion span records each branch's eligible Article Chunk count and ordered IDs, plus the ordered fused output IDs. Order carries rank without a duplicate rank field.
- [ ] The recorded eligible and fused IDs agree with the actual retrieval result when branches contain duplicate IDs, return more than their candidate limits, or complete in different orders.
- [ ] An Evidence Assembly span records selected IDs, omitted IDs and reasons, relevant Coverage Description, applied character and passage limits, and measured context use.
- [ ] A failed or deadline-exhausted fusion or Evidence Assembly result has an explicit stage status, stable failure kind, and safe diagnostic. An Evidence Assembly failure is not represented as a Retrieval Answer.
- [ ] Custom application attributes omit raw scores, candidate retrieval routes, and full passage text at this stage; the final answer observation owns the selected passage snapshot.
- [ ] ASGI-level tests inspect captured Logfire spans while driving the real Chat Session and deterministic fake branches and Grounding Evidence storage. They verify selection and failure facts without testing private telemetry helper calls.

## Blocked by

- [03 — Trace retrieval branch outcomes](03-trace-retrieval-branch-outcomes.md).
