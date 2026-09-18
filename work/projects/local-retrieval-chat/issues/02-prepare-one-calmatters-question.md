# 02 — Prepare one CalMatters question for approval

Labels: completed

## Parent

[Local Retrieval Chat](../PRD.md)

## What to build

Let a maintainer type one California political question into the browser and see
the Query Rewrite Proposal produced by the real Chat Session. The application
assembles its dependencies and CalMatters coverage at startup, maps the browser
conversation to an in-memory Chat Session, and renders the typed preparation
outcome without creating another orchestration path.

This slice makes the first useful vertical path through the stock composer,
FastAPI adapter, existing Chat Session, Query Rewriter, Chat Agent assessment,
and browser response. It stops at approval; retrieval remains a later slice.

## Acceptance criteria

- [x] Application startup assembles one Query Rewriter, Chat Agent, Retrieval
      Coordinator, database dependency set, and fixed Model Deployment set, and
      application shutdown releases the resources it owns.
- [x] Startup fails with a dependency-specific explanation when the SQLite
      document store is unreadable, Neo4j is unreachable, the Query Rewriter or
      Chat Agent deployment is unreachable, or CalMatters coverage cannot be
      loaded and refreshed.
- [x] Dense embedding, structural construction, and branch-specific index
      availability do not gate startup; their failures retain the retrieval
      contract's branch-level behavior.
- [x] One authored CalMatters Coverage Description is loaded at startup and its
      measured article count and date range are refreshed from current data.
- [x] CalMatters is supplied as relevant to every version-one question, and no
      monthly coverage is supplied.
- [x] The first ordinary message for a new browser conversation creates exactly
      one in-memory Chat Session and invokes its preparation operation.
- [x] An awaiting-approval outcome exposes only the public Query Approval. The
      internal relational route is not emitted to the browser.
- [x] Deferred coverage and its recoverable portion are shown with an otherwise
      approvable proposal.
- [x] Declined and unavailable-rewrite outcomes are presented without offering
      approval or starting retrieval.
- [x] The browser exposes neither a model picker nor optional tool controls.
- [x] ASGI-level tests drive the preparation outcomes with a deterministic Chat
      Session factory and assert protocol events rather than frontend markup or
      private adapter state.

## Blocked by

- [01 — Launch the secured local chat shell](01-launch-secured-local-chat-shell.md).

## Comments

2026-09-18: Implemented application-lifetime dependency assembly, authored and
measured CalMatters coverage, and the first browser-message path through the
real Chat Session. The adapter emits only the public Query Approval, includes
Deferred disclosures, and ends Declined or unavailable rewrites without an
approval event. Deterministic tests exercise the FastAPI ASGI boundary with
injected startup contexts and Chat Session factories.

The independent Spec review found no ticket gap or scope creep. The Standards
review found that the first implementation bypassed the repository's shared
Model Reachability Check policy. The review fix now probes only local model
deployments, treats every HTTP response as proof of reachability, honors
`SKIP_MODEL_REACHABILITY_CHECK`, and leaves OpenRouter reachability to its first
real request. The two smell notes did not justify changes: extracting the three
typed model-cache branches would add higher-order plumbing, and a collection
type for the one supported CalMatters collection would be speculative.

Review verification passed 64 affected tests, changed-feature-file Ruff,
formatting, and type checks, `git diff --check`, and the full deterministic
suite: 1,231 passed, 47 skipped, with one existing Pydantic AI sampling warning.
No live model, Neo4j, browser, CDN, or retrieval-quality check was run, as this
ticket's deterministic boundary requires.
