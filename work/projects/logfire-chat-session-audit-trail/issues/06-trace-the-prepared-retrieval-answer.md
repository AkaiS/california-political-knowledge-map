# 06 — Trace the prepared Retrieval Answer

Labels: ready-for-agent

## Parent

[Logfire Chat Session Audit Trail](../PRD.md)

## What to build

Make the answer boundary inspectable after Evidence Assembly succeeds. A maintainer can see the Chat Agent guidance operation beside its model spans and inspect the exact Retrieval Answer text the application prepared for the browser, together with the selected stored passages and Source Article citations that informed it. The observation is made before text emission and does not claim delivery.

## Acceptance criteria

- [ ] A Chat Agent guidance span carries the Chat Session ID, result status, and safe failure kind when needed; existing Pydantic AI spans provide model messages, retries, and token use.
- [ ] Only a prepared Retrieval Answer emits an answer observation. It contains the exact rendered browser text, selected stored Article Chunk passages with their `stored_chunk` provenance marker, and Source Article citations.
- [ ] A zero-passage Retrieval Answer still emits an answer observation with an empty selected-source snapshot. An Evidence Assembly failure emits none.
- [ ] The answer observation occurs after rendering and before browser text emission. Neither the observation nor its tests claim that the browser received, displayed, or read the text.
- [ ] A representative large answer is checked for readable structured attributes and Logfire ingest-size limits; required content is not silently shortened by application code.
- [ ] ASGI-level tests compare captured answer data with the actual response prepared for emission and verify unchanged browser output when telemetry capture is unavailable after startup. No live Logfire project or browser automation is required.

## Blocked by

- [05 — Trace fusion and Evidence Assembly](05-trace-fusion-and-evidence-assembly.md).
