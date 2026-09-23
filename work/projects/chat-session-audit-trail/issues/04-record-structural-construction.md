# 04 — Record structural construction

Labels: ready-for-agent

## Parent

[Chat Session Audit Trail](../PRD.md)

## What to build

Expose the varying results inside typed structural retrieval. A maintainer should be able to inspect which ontology pieces were selected, how the question was wired and bound, which validated query and bound values reached Neo4j, and whether execution or hydration failed. These are separate Audit Stage Records under the same Chat Session audit ID.

## Acceptance criteria

- [ ] Schema filtering, typed selection, wiring, binding, validated query construction, execution, and hydration each record their result or safe failure with their own stage ID and timing.
- [ ] Saved metadata includes selected ontology pieces, wiring and binding decisions, validated query text and bound values, and database and hydration outcomes.
- [ ] Stages that make model calls record token usage when available. The local audit excludes raw provider requests and responses, raw model output, and embedding vectors.
- [ ] A structural-stage failure retains its stage, failure kind, and safe diagnostic. A failed structural branch does not erase completed full-text or dense evidence or change the browser's answer behavior.
- [ ] ASGI-level tests drive a relational question through scripted structural agents and fake graph responses, then inspect the saved stages. Controlled failures show which structural step stopped without asserting private helper calls.

## Blocked by

- [01 — Open and inspect a Chat Session Audit Trail](01-open-and-inspect-a-chat-session-audit-trail.md).
