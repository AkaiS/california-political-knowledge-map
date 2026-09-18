# 03 — Approve and inspect a Retrieval Answer

Labels: completed

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

- [x] Approving the public Query Approval invokes the Chat Session's approval
      operation exactly once and cannot consume the same approval again.
- [x] The browser receives a presentation-only Search details operation in a
      running state while the non-streaming approval operation is in progress.
- [x] A completed Retrieval Answer presents numbered Source Article links and
      the verified passages selected by Evidence Assembly.
- [x] Deferred explanations and every existing user-safe branch-failure
      disclosure remain visible in the main answer.
- [x] A dedicated safe serializer includes retrieval routes, branch-local ranks,
      supporting graph claims, relevant Coverage Description facts, and branch
      outcomes.
- [x] Search details exclude unverified grounding text, raw exceptions, internal
      model output, and detailed failure diagnostics.
- [x] The adapter emits the completed safe value as a collapsible Search details
      operation and never includes it in model context or registers it as a Chat
      Agent tool.
- [x] Evidence Assembly failure is rendered without presenting unverified audit
      candidates as passages.
- [x] The final answer and completed Search details are emitted after approval
      returns; version one does not change the core to stream model tokens.
- [x] ASGI-level tests cover approval, answer rendering, safe-detail inclusion
      and exclusion, partial failures, and assembly failure using the existing
      public Pydantic outcome types.

## Blocked by

- [02 — Prepare one CalMatters question for approval](02-prepare-one-calmatters-question.md).

## Comments

2026-09-18: Implemented one-shot approval through the existing Chat Session,
with a running presentation-only Search details operation followed by the typed
Retrieval Answer and safe completed details. The answer renders numbered Source
Article links, verified passages, relevance notes, disagreements, Deferred and
branch-failure disclosures, while assembly failure excludes unverified audit
candidates. Search details retains routes, branch ranks, graph claims, relevant
coverage, and branch outcomes without candidate wording or failure diagnostics.

The independent Spec review found no missing, incorrect, or out-of-scope
behavior. The Standards review found three valid issues: the adapter protocol
used preparation-only terminology after gaining approval behavior, the Markdown
escaping helper's name understated its contract, and the ASGI answer tests
repeated their prepare-and-approve ceremony. The review fix renamed both seams
and extracted the shared test interaction helper.

Review verification passed 30 focused ASGI tests, changed-feature-file Ruff,
formatting, and type checks, `git diff --check`, and the full deterministic
suite: 1,245 passed, 47 skipped, with one existing Pydantic AI sampling warning.
No browser, live model, Neo4j, CDN, or retrieval-quality check was run, as this
ticket's deterministic boundary requires.
