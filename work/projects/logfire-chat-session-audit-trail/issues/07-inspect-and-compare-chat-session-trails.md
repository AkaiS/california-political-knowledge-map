# 07 — Inspect and compare Chat Session trails

Labels: completed

## Parent

[Logfire Chat Session Audit Trail](../PRD.md)

## What to build

Give maintainers a documented way to find one Chat Session's application observations in Logfire, follow the related model traces, and compare sessions across code and configuration changes. The inspection guidance distinguishes saved facts from missing or expired telemetry and makes the configured retention visible. It does not add another audit store or command-line read path.

## Acceptance criteria

- [x] Document a Logfire SQL search by application Chat Session ID that returns named application stages with their times, statuses, and trace IDs, allowing navigation into each request trace.
- [x] Document queries or filters for observation time, code revision, Model Deployment, Retrieval Answer presence, and failed stage. The query contract uses attributes emitted by the preceding tickets.
- [x] Explain that separate preparation and approval traces share an application ID, while parallel retrieval branches have no total completion order.
- [x] Explain Logfire's configured retention and best-effort delivery. A missing Retrieval Answer observation receives no inferred closing cause or browser-delivery claim.
- [x] Describe how a maintainer can save the useful search in Logfire. No custom Query API client, local audit database, or audit CLI is introduced.
- [x] Offline tests or captured-span assertions verify the fields and identities that the documented queries depend on. No live Logfire project, browser, or computer-use verification is required.

## Blocked by

- [04 — Trace structural construction](04-trace-structural-construction.md).
- [06 — Trace the prepared Retrieval Answer](06-trace-the-prepared-retrieval-answer.md).

## Comments

Implemented on 2026-09-24. The [inspection guide](../../../../docs/chat-session-trails.md),
linked from the main README, provides application-ID, session-cohort, and
failed-stage SQL, plus a Live saved-search predicate. The queries use emitted
schema version 1 fields. They preserve NULL statuses, include returned rewrite
unavailability, and distinguish failed stage observations from failed sessions.

The guide explains separate request traces and native model ancestry, concurrent
branch timing, and the prepared-answer event's possible separate trace. Cohort
answer presence is explicitly limited to the selected window. A missing start
record can exclude a session from that cohort while its other observations
remain searchable by application ID. Retention guidance identifies where to
confirm the destination project's policy; it does not invent a configured
duration. Saving a search does not preserve its results or extend retention.

The selected public seam is `POST /api/chat` with real Chat Session coordination,
scripted models, fake graph/transport boundaries, and captured Logfire spans.
Three vertical red-green slices execute the documented SQL against a test-only
in-memory SQLite projection of those observations. They verify cross-request
identity, named stages and statuses, changed startup revisions and deployments,
answer presence before and after approval, and structural, guidance, and rewrite
failures. No runtime store, client, or command was added.

These tests verify the portable SQL/JSON subset and emitted field contract, not
Logfire ingestion or its query engine. Navigation, SQL syntax, saved searches,
and retention guidance were checked against official Logfire documentation on
2026-09-24. No live project, model provider, Neo4j, browser, or computer use was
needed.

Validation: 76 focused trail tests passed. Changed-file Ruff, formatting,
`ty 0.0.83`, and `git diff --check` passed. The single final
`uv run --no-sync pytest -q` run passed with 1,342 tests, 47 skips, and the
existing Pydantic AI sampling warning. Commands use `uv` with the writable
`/private/tmp/ca-map-uv-cache` cache; type checks use the existing cached `ty`
binary through `uv run --no-sync`.
