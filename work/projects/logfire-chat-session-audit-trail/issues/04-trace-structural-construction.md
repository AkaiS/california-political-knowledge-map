# 04 — Trace structural construction

Labels: completed

## Parent

[Logfire Chat Session Audit Trail](../PRD.md)

## What to build

Within a structural retrieval branch, let a maintainer see how the approved relational question became a validated graph query and Grounding Evidence. The trace separates ontology filtering, typed selection, wiring, binding, validation, database execution, and hydration, so a zero result or failure can be located without treating model output as an accepted query.

## Acceptance criteria

- [x] Structural application stages appear beneath the structural branch span and carry the same Chat Session ID, with native span relationships and actual timing.
- [x] Filtering and typed selection record the accepted ontology pieces. Wiring and binding record their accepted application results, not a second copy of raw provider messages.
- [x] Validation records the query text and bound values that were approved for read-only database execution, or a safe validation failure when no query was approved.
- [x] Database execution records the database identity and returned row count. Hydration records the produced candidate count or its failure.
- [x] Each returned failure or raised exception is assigned to the stage where it occurred with a stable kind and safe diagnostic. Pydantic AI child spans retain model retries and token details.
- [x] An ASGI-level test runs a relational question through scripted structural agents and fake graph data, then inspects captured spans for accepted decisions. Focused failure cases distinguish validation, database, deadline, and hydration outcomes without a live model or Neo4j.

## Blocked by

- [03 — Trace retrieval branch outcomes](03-trace-retrieval-branch-outcomes.md).


## Comments

Implemented on 2026-09-24. The public seam is `POST /api/chat` through
preparation and approval, with real Chat Session and retrieval coordination,
scripted structural agents, a fake Neo4j driver, and an offline Logfire
exporter. The existing model and driver injection points were sufficient;
no public API or acceptance meaning changed.

`chat_session.structural_stage` spans carry the session identity and the actual
stage timing. Filtering and selection record accepted pieces, wiring and
binding record accepted typed results, and each compiler validation records
its approved query and parameters or a safe failure. Validation remains inside
the binder's output validator, preserving the existing correction boundary and
Pydantic AI ancestry. Execution records database identity and row count;
hydration records candidate count. Stage failures preserve stable kinds,
including the actual stage interrupted by the shared deadline. The later PR
review left legitimate Bill `session` values and validated query text subject
to Logfire's default scrubbing.

Seventeen ASGI cases cover relational Grounding Evidence, empty success,
corrected binding, rejection exhaustion, all four model stages, database
failure, database timeout, binding timeout, shared deadline cancellation,
hydration failure, and an unexpected database exception. Rejected values and
raw exception text are absent from custom attributes; native model spans keep
the retry activity. No live model, Neo4j, browser, or Logfire project was used.

Validation: 118 focused tests passed. Changed-file Ruff, formatting,
`ty 0.0.83`, and `git diff --check` passed. The single final
`uv run --no-sync pytest -q` run passed with 1,314 tests, 47 skips, and the
existing Pydantic AI sampling warning. Commands used `uv` with the writable
`/private/tmp/ca-map-uv-cache` cache. The initial `uvx` type-check invocation
hit a sandbox system-configuration panic; running the existing cached `ty`
binary through `uv run --no-sync` passed.
