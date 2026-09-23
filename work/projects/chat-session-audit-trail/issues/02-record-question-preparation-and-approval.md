# 02 — Record question preparation and approval

Labels: ready-for-agent

## Parent

[Chat Session Audit Trail](../PRD.md)

## What to build

Show how one original question became the approved Query Rewrite. Record each proposal, its question-policy and coverage assessment, and the person's approval, rejection, or correction in the Chat Session Audit Trail. Successive Query Rewrite proposals have attempt numbers; no other stages receive them.

## Acceptance criteria

- [ ] Each Query Rewrite proposal records its text, relational route, result or safe failure, timing, model token usage when available, and its one-based proposal attempt number within the Chat Session.
- [ ] Assessment records distinguish allowed, Declined, and Deferred results and retain explanations and recoverable portions where supplied.
- [ ] Approval records identify the Query Rewrite that retrieval used. Rejection and correction records preserve the feedback that led to a later proposal.
- [ ] A Declined question or unavailable rewrite leaves the stages that were saved without an invented Retrieval Answer or session-closing record.
- [ ] Records share ticket 01's application audit ID and unique stage IDs. No global stage ordinal is introduced.
- [ ] ASGI-level tests drive an initial proposal, rejection and correction, a second proposal, and approval through a real Chat Session; inspect the saved stages through the public audit read path. Separate tests cover Declined and unavailable rewrites.

## Blocked by

- [01 — Open and inspect a Chat Session Audit Trail](01-open-and-inspect-a-chat-session-audit-trail.md).
