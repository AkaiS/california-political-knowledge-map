# 01 — Start a searchable Chat Session trail

Labels: ready-for-agent

## Parent

[Logfire Chat Session Audit Trail](../PRD.md)

## What to build

When a person asks the first valid question in a Chat Session, make that session findable in Logfire by one application-generated ID. Record the original question and the effective conditions under which the session began. This is the first useful path from the browser request through a real Chat Session to captured telemetry. It establishes the identity later slices carry across separate requests and stages.

Implementation begins from the pre-audit branch point with this spec and ticket set committed. The old local audit store and CLI are absent from this baseline.

## Acceptance criteria

- [ ] The first accepted question creates one Chat Session ID that is distinct from browser conversation and Logfire trace IDs. Invalid submissions create no Chat Session trail.
- [ ] A Logfire start observation contains that ID, the original question, observation time, effective code revision and dirty state, resolved non-secret Model Deployments, prompt hashes, fusion settings, Evidence Assembly limits, and the already measured Coverage Description with its observation time.
- [ ] Capturing start settings makes no additional corpus, index, or model query solely for telemetry.
- [ ] A manual preparation span carries the same ID and contains the Pydantic AI agent spans produced during preparation. No span stays open waiting for a person's approval.
- [ ] An ASGI-level test drives the real Chat Session with scripted agents and inspects in-process Logfire capture for the ID, effective settings, and trace relationship; it needs no live Logfire project.
- [ ] Existing browser preparation behavior is unchanged, and the domain description of the Chat Session Audit Trail states Logfire's retention-bounded, best-effort meaning.

## Blocked by

None — can start immediately.
