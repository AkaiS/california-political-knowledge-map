# 06 — Trace the prepared Retrieval Answer

Labels: completed

## Parent

[Logfire Chat Session Audit Trail](../PRD.md)

## What to build

Make the answer boundary inspectable after Evidence Assembly succeeds. A maintainer can see the Chat Agent guidance operation beside its model spans and inspect the Retrieval Answer text the application prepared for the browser, together with the selected stored passages and Source Article citations that informed it. Logfire may redact sensitive-looking text. The observation is made before text emission and does not claim delivery.

## Acceptance criteria

- [x] A Chat Agent guidance span carries the Chat Session ID, result status, and safe failure kind when needed; existing Pydantic AI spans provide model timing, retries, and token use without prompt, completion, or tool content.
- [x] Only a prepared Retrieval Answer emits an answer observation. It contains rendered browser text, selected stored Article Chunk passages with their `stored_chunk` provenance marker, and Source Article citations, subject to Logfire scrubbing.
- [x] A zero-passage Retrieval Answer still emits an answer observation with an empty selected-source snapshot. An Evidence Assembly failure emits none.
- [x] The answer observation occurs after rendering and before browser text emission. Neither the observation nor its tests claim that the browser received, displayed, or read the text.
- [x] A representative large answer is checked for readable structured attributes and Logfire ingest-size limits; required content is not silently shortened by application code.
- [x] ASGI-level tests compare captured answer data with the actual response prepared for emission and verify unchanged browser output when telemetry capture is unavailable after startup. No live Logfire project or browser automation is required.

## Blocked by

- [05 — Trace fusion and Evidence Assembly](05-trace-fusion-and-evidence-assembly.md).

## Comments

Implemented on 2026-09-24. The public test seam is `POST /api/chat` through
preparation and approval with real Chat Session, retrieval coordination, and
Evidence Assembly. Scripted model responses, fake retrieval branches and stored
Grounding Evidence, and an offline Logfire exporter use existing boundaries.
The ASGI `send` boundary checks the observation before the first answer text
emission. It establishes no browser receipt, display, or reading.

`chat_session.guidance` contains the existing Chat Agent model run under
`chat_session.approve`. It records success only after the Retrieval Answer
validates, or a safe diagnostic with `transport`, `provider`, `model_output`,
`validation`, or `unexpected` failure kind. The existing failure response remains
intact; Logfire exception events are suppressed after the PR privacy review.

After rendering, `chat_session.answer_prepared` records `rendered_text` and
`selected_sources`, grouped by Source Article citation. Each passage includes
its Article Chunk ID, stored text, and `stored_chunk` provenance. The
snapshot excludes candidates, ranking, routes, and raw model payloads. A
zero-passage answer records an empty source list; assembly or guidance failure
records no prepared answer. Political text containing `session` may now be
redacted by Logfire scrubbing.

The browser session protocol now declares the Chat Session ID already exposed
by the concrete session. The post-render event joins the bounded core approval
operation by this ID. It may have a separate native trace because core approval
has returned before browser rendering. Guidance and model spans retain their
native approval ancestry; this adds no retained trace-context API or span held
open across requests.

The twelve-source fixture uses between 20,000 and 24,000 of the default 24,000
context characters and produces an answer longer than 12,000 UTF-8 bytes. Its
encoded OTLP record and exported attributes remain below Logfire's
[documented 10 MB ingest limit](https://pydantic.dev/docs/logfire/reference/limits/),
checked on 2026-09-24. The separate 512-byte display-message limit affects only
the stable event name here. These measurements verify this representative
fixture, not every possible configured limit or model output. Application code
does not truncate either snapshot field.

Eleven ASGI cases cover guidance and native model ancestry, five failure kinds,
exact stored and rendered text, pre-emission timing, empty answers, assembly
failure, and exporter exceptions after startup. With the exporter unavailable,
answer text, Search details, stream event types, and terminal session behavior
match the working-exporter case. No live provider, Neo4j, Logfire project, or
browser automation was used.

Validation: 116 focused tests passed. Changed-file Ruff, formatting,
`ty 0.0.83`, and `git diff --check` passed. The single final
`uv run --no-sync pytest -q` run passed with 1,339 tests, 47 skips, and the
existing Pydantic AI sampling warning. Commands use `uv` with the writable
`/private/tmp/ca-map-uv-cache` cache; type checks use the existing cached `ty`
binary through `uv run --no-sync`.
