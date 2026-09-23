# 05 — Record Evidence Assembly

Labels: ready-for-agent

## Parent

[Chat Session Audit Trail](../PRD.md)

## What to build

Show how fused candidates became the evidence supplied to the Chat Agent. Record selected and omitted Article Chunk IDs, why a candidate was omitted when known, the context budget and measured use, relevant coverage, and any Evidence Assembly failure. The audit observes the existing deterministic selection without changing it.

## Acceptance criteria

- [ ] A successful Evidence Assembly record includes its selected IDs, omitted IDs and reasons, relevant Coverage Description entries, applied limits, and measured context use.
- [ ] An oversized passage omitted by the character budget is distinguishable from a candidate left out after the passage limit. Later eligible passages remain selectable under the existing rules.
- [ ] A hydration, provenance, coverage, or budget failure creates a safe failed-stage record without presenting unverified candidate wording as a quotation or changing retrieval branch outcomes.
- [ ] The Audit Stage Record carries the Chat Session audit ID, unique stage ID, timing, and result status. It does not duplicate the complete Evidence Package or raw provider payloads.
- [ ] ASGI-level tests use a real Chat Session with fake retrieval and Grounding Evidence storage, then inspect saved audit data for selected, omitted, empty, and failed assembly cases. Existing evidence-selection behavior remains unchanged.

## Blocked by

- [01 — Open and inspect a Chat Session Audit Trail](01-open-and-inspect-a-chat-session-audit-trail.md).
