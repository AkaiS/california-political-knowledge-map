# 02 — Trace question preparation and approval

Labels: ready-for-agent

## Parent

[Logfire Chat Session Audit Trail](../PRD.md)

## What to build

Let a maintainer follow one original question through successive Query Rewrite Proposals, question-policy and coverage assessments, a person's correction, and the approved Query Rewrite in Logfire. The observations remain joined to the Chat Session across separate browser requests. A Declined question or unavailable rewrite leaves its observed preparation stages without an invented closing outcome.

## Acceptance criteria

- [ ] Each Query Rewrite Proposal records its text, relational route, result status, and one-based attempt number within the Chat Session. Other stages do not receive proposal attempt numbers as their own sequence.
- [ ] Each question assessment records its result and refers to the proposal it assessed, including Declined and Deferred explanations when present.
- [ ] A correction and an approval each refer to the applicable proposal. The approved wording is explicit, and retrieval continues to use only that approved Query Rewrite.
- [ ] Preparation, correction, and approval operations have separate bounded spans with the same Chat Session ID. Model calls appear beneath the application operation that invoked them; no span covers the person's waiting time.
- [ ] Returned unavailability and safe failure kinds are recorded even when no exception escapes. Custom attributes do not duplicate raw model messages, retries, or token details already emitted by Pydantic AI.
- [ ] ASGI-level tests exercise an initial proposal, correction, second proposal, approval, Declined assessment, unavailable rewrite, and abandoned approval. Captured spans agree with browser outcomes without relying on a live Logfire project or a particular exporter schedule.

## Blocked by

- [01 — Start a searchable Chat Session trail](01-start-a-searchable-chat-session-trail.md).
