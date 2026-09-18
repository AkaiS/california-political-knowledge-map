# 03 — Approve and inspect a Retrieval Answer

Labels: ready-for-agent

## Parent

[Local Retrieval Chat](../PRD.md)

## What to build

Let a maintainer approve the displayed Query Rewrite and receive one inspectable
Retrieval Answer in the browser. Approval drives the existing Chat Session once;
the adapter shows that search is in progress, waits for the non-streaming core
operation, and then presents the verified answer and its safe retrieval details.

The main response is for reading the evidence. Expandable Search details are for
understanding how the evidence was found. Neither presentation creates a new
retrieval contract or becomes a tool available to the Chat Agent.

## Acceptance criteria

- [ ] Approving the public Query Approval invokes the Chat Session's approval
      operation exactly once and cannot consume the same approval again.
- [ ] The browser receives a presentation-only Search details operation in a
      running state while the non-streaming approval operation is in progress.
- [ ] A completed Retrieval Answer presents numbered Source Article links and
      the verified passages selected by Evidence Assembly.
- [ ] Deferred explanations and every existing user-safe branch-failure
      disclosure remain visible in the main answer.
- [ ] A dedicated safe serializer includes retrieval routes, branch-local ranks,
      supporting graph claims, relevant Coverage Description facts, and branch
      outcomes.
- [ ] Search details exclude unverified grounding text, raw exceptions, internal
      model output, and detailed failure diagnostics.
- [ ] The adapter emits the completed safe value as a collapsible Search details
      operation and never includes it in model context or registers it as a Chat
      Agent tool.
- [ ] Evidence Assembly failure is rendered without presenting unverified audit
      candidates as passages.
- [ ] The final answer and completed Search details are emitted after approval
      returns; version one does not change the core to stream model tokens.
- [ ] ASGI-level tests cover approval, answer rendering, safe-detail inclusion
      and exclusion, partial failures, and assembly failure using the existing
      public Pydantic outcome types.

## Blocked by

- [02 — Prepare one CalMatters question for approval](02-prepare-one-calmatters-question.md).
