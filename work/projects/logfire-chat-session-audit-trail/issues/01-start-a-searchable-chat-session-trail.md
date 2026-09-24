# 01 — Start a searchable Chat Session trail

Labels: completed

## Parent

[Logfire Chat Session Audit Trail](../PRD.md)

## What to build

When a person asks the first valid question in a Chat Session, make that session findable in Logfire by one application-generated ID. Record the original question and the effective conditions under which the session began. This is the first useful path from the browser request through a real Chat Session to captured telemetry. It establishes the identity later slices carry across separate requests and stages.

Implementation begins from the pre-audit branch point with this spec and ticket set committed. The old local audit store and CLI are absent from this baseline.

## Acceptance criteria

- [x] The first accepted question creates one Chat Session ID that is distinct from browser conversation and Logfire trace IDs. Invalid submissions create no Chat Session trail.
- [x] A Logfire start observation contains that ID, the original question, observation time, effective code revision and dirty state, resolved non-secret Model Deployments, prompt hashes, fusion settings, Evidence Assembly limits, and the already measured Coverage Description with its observation time.
- [x] Capturing start settings makes no additional corpus, index, or model query solely for telemetry.
- [x] A manual preparation span carries the same ID and contains the Pydantic AI agent spans produced during preparation. No span stays open waiting for a person's approval.
- [x] An ASGI-level test drives the real Chat Session with scripted agents and inspects in-process Logfire capture for the ID, effective settings, and trace relationship; it needs no live Logfire project.
- [x] Existing browser preparation behavior is unchanged, and the domain description of the Chat Session Audit Trail states Logfire's retention-bounded, best-effort meaning.

## Blocked by

None — can start immediately.

## Comments

2026-09-24: Implemented `chat_session.started` and `chat_session.prepare`, joined
by the UUID `chat_session_id` and marked with `audit_schema_version=1`. Startup
retains its code state, resolved Model Deployments, prompt hashes, fusion and
Evidence Assembly settings, and coverage observation time. The first accepted
question records those values with its original text and acceptance observation
time. Unavailable Git metadata stays unknown. Preparation closes before approval
and contains the existing Pydantic AI agent spans.

The ASGI tests exercise real Chat Sessions with scripted model responses and an
in-process Logfire exporter. They cover invalid requests, distinct accepted
sessions, unchanged browser preparation, nested agent spans, effective settings,
unchanged corpus/model request counts, OpenRouter policy without credentials,
unavailable Git metadata, and exporter failure. Capture also verifies that the
default scrubber cannot redact the Chat Session ID or political questions about
a legislative session; the exception applies only to declared audit fields.

Validation: 147 focused tests passed; changed-file Ruff and `ty 0.0.83` checks
passed; `uv run --no-sync pytest -q` passed with 1,272 tests, 47 skipped, and the
existing Pydantic AI sampling warning. No live Logfire, model, Neo4j, or browser
check was needed.
