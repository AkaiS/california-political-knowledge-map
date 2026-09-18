# 04 — Reject and revise a Query Rewrite Proposal

Labels: completed

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

- [x] Rejecting a proposal changes the browser conversation to an
      awaiting-correction state and clearly asks for the desired change.
- [x] Rejection alone does not call the Chat Session's rejection operation with
      an invented or empty correction.
- [x] The next ordinary composer message is passed as the correction to the core
      rejection operation, preserving its atomic rejection-and-correction
      contract.
- [x] After recording the correction, the same Chat Session prepares and
      presents a new Query Rewrite Proposal.
- [x] The revised proposal exposes only its public Query Approval and requires a
      separate approval before retrieval can start.
- [x] A correction can never be interpreted directly as an approved Query
      Rewrite or a second political question.
- [x] Another rejection may repeat the same two-step interaction without
      creating a second Chat Session for the browser conversation.
- [x] The awaiting-correction state remains process-local and introduces no
      transcript or pending-approval persistence.
- [x] ASGI-level tests cover rejection, correction, another proposal, repeated
      correction, and the absence of retrieval before a later approval.

## Blocked by

- [02 — Prepare one CalMatters question for approval](02-prepare-one-calmatters-question.md).

## Comments

2026-09-18: Implemented deterministic two-step rejection through the stock chat
protocol. Rejecting a Query Rewrite Proposal consumes its approval, emits the
denied operation, and asks for a correction without calling the core or entering
retrieval. The next text-only composer message is passed to the same Chat
Session's atomic rejection operation, which prepares a fresh public proposal
that requires its own approval. The process-local loop can repeat without
creating another Chat Session.

The independent Spec review found no missing, incorrect, or out-of-scope
behavior. The Standards review found one valid judgment-call issue: question and
correction composer text were parsed by duplicated logic. The review fix moved
that shared rule behind one adapter helper so both paths continue to accept only
nonempty text messages.

Review verification passed 31 focused ASGI tests, changed-feature-file Ruff,
formatting, and type checks, `git diff --check`, and the full deterministic
suite: 1,246 passed, 47 skipped, with one existing Pydantic AI sampling warning.
No browser, live model, Neo4j, CDN, or retrieval-quality check was run, as this
ticket's deterministic boundary requires.
