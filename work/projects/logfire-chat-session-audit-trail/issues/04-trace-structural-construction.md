# 04 — Trace structural construction

Labels: ready-for-agent

## Parent

[Logfire Chat Session Audit Trail](../PRD.md)

## What to build

Within a structural retrieval branch, let a maintainer see how the approved relational question became a validated graph query and Grounding Evidence. The trace separates ontology filtering, typed selection, wiring, binding, validation, database execution, and hydration, so a zero result or failure can be located without treating model output as an accepted query.

## Acceptance criteria

- [ ] Structural application stages appear beneath the structural branch span and carry the same Chat Session ID, with native span relationships and actual timing.
- [ ] Filtering and typed selection record the accepted ontology pieces. Wiring and binding record their accepted application results, not a second copy of raw provider messages.
- [ ] Validation records the query text and bound values that were approved for read-only database execution, or a safe validation failure when no query was approved.
- [ ] Database execution records the database identity and returned row count. Hydration records the produced candidate count or its failure.
- [ ] Each returned failure or raised exception is assigned to the stage where it occurred with a stable kind and safe diagnostic. Pydantic AI child spans retain model retries and token details.
- [ ] An ASGI-level test runs a relational question through scripted structural agents and fake graph data, then inspects captured spans for accepted decisions. Focused failure cases distinguish validation, database, deadline, and hydration outcomes without a live model or Neo4j.

## Blocked by

- [03 — Trace retrieval branch outcomes](03-trace-retrieval-branch-outcomes.md).
