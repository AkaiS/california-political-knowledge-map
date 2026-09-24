# 02 — Record question preparation and approval

Labels: completed

## Parent

[Chat Session Audit Trail](../PRD.md)

## What to build

Show how one original question became the approved Query Rewrite. Record each Query Rewrite Proposal, its question-policy and coverage assessment, the person's approval, and any correction in the Chat Session Audit Trail. Successive proposals have attempt numbers; no other stages receive them. A later numbered proposal makes an earlier rejection implicit, so no separate rejection record is needed.

## Acceptance criteria

- [x] Each Query Rewrite Proposal records its text, relational route, result or safe failure, timing, model token usage when available, and its one-based proposal attempt number within the Chat Session.
- [x] Assessment records distinguish allowed, Declined, and Deferred results and retain explanations and recoverable portions where supplied.
- [x] Approval records identify the Query Rewrite that retrieval used. Correction records preserve the feedback that led to a later proposal; numbered proposals make rejection implicit.
- [x] A Declined question or unavailable rewrite leaves the stages that were saved without an invented Retrieval Answer or session-closing record.
- [x] Records share ticket 01's application audit ID and unique stage IDs. No global stage ordinal is introduced.
- [x] ASGI-level tests drive an initial proposal, rejection and correction, a second proposal, and approval through a real Chat Session; inspect the saved stages through the public audit read path. Separate tests cover Declined and unavailable rewrites.

## Blocked by

- [01 — Open and inspect a Chat Session Audit Trail](01-open-and-inspect-a-chat-session-audit-trail.md).
