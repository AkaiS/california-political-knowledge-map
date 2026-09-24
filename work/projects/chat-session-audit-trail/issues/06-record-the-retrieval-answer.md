# 06 — Record the Retrieval Answer

Labels: completed

## Parent

[Chat Session Audit Trail](../PRD.md)

## What to build

When the Chat Agent produces a Retrieval Answer, start one final Audit Stage Record before emitting the browser answer text. Preserve the exact rendered answer and the selected stored Article Chunk passages and Source Article citations as they stood for that response. Record Chat Agent guidance and its safe failure separately, so a session without a Retrieval Answer is left as saved stages rather than assigned an inferred ending.

## Acceptance criteria

- [x] The Chat Agent guidance stage records timing, result or safe failure, and model token usage where available.
- [x] Each Retrieval Answer starts one final background insert before its browser answer text is emitted. The record includes the exact rendered text and selected stored passages and citations, including an answer with zero selected passages.
- [x] Saved passage wording retains its stored Article Chunk provenance and is not described as verbatim Publication wording.
- [x] An Evidence Assembly failure, Declined question, unavailable rewrite, abandoned approval, or unexpected model error creates no Retrieval Answer record. The CLI does not infer a reason from that absence.
- [x] Audit insertion delay or failure does not alter answer rendering, Search details, browser delivery, or Chat Session cleanup. The record does not claim that a browser received or read the answer.
- [x] ASGI-level tests use a real Chat Session, scripted agents, fake retrieval dependencies, and a temporary audit database to inspect the saved snapshot and verify unchanged browser output when audit storage fails.

## Blocked by

- [01 — Open and inspect a Chat Session Audit Trail](01-open-and-inspect-a-chat-session-audit-trail.md).
