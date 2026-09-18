# 04 — Reject and revise a Query Rewrite Proposal

Labels: ready-for-agent

## Parent

[Local Retrieval Chat](../PRD.md)

## What to build

Let a maintainer reject a Query Rewrite Proposal and describe the desired change
through the stock chat composer. Rejection places the browser conversation into
an awaiting-correction state. The next ordinary message supplies the correction
to the existing Chat Session, which then produces another proposal for explicit
approval.

This remains deterministic adapter behavior. The correction is feedback to the
Query Rewriter, not a replacement query and not permission to retrieve.

## Acceptance criteria

- [ ] Rejecting a proposal changes the browser conversation to an
      awaiting-correction state and clearly asks for the desired change.
- [ ] Rejection alone does not call the Chat Session's rejection operation with
      an invented or empty correction.
- [ ] The next ordinary composer message is passed as the correction to the core
      rejection operation, preserving its atomic rejection-and-correction
      contract.
- [ ] After recording the correction, the same Chat Session prepares and
      presents a new Query Rewrite Proposal.
- [ ] The revised proposal exposes only its public Query Approval and requires a
      separate approval before retrieval can start.
- [ ] A correction can never be interpreted directly as an approved Query
      Rewrite or a second political question.
- [ ] Another rejection may repeat the same two-step interaction without
      creating a second Chat Session for the browser conversation.
- [ ] The awaiting-correction state remains process-local and introduces no
      transcript or pending-approval persistence.
- [ ] ASGI-level tests cover rejection, correction, another proposal, repeated
      correction, and the absence of retrieval before a later approval.

## Blocked by

- [02 — Prepare one CalMatters question for approval](02-prepare-one-calmatters-question.md).
