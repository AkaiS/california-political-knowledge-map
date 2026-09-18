# 02 — Prepare one CalMatters question for approval

Labels: ready-for-agent

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

- [ ] Application startup assembles one Query Rewriter, Chat Agent, Retrieval
      Coordinator, database dependency set, and fixed Model Deployment set, and
      application shutdown releases the resources it owns.
- [ ] Startup fails with a dependency-specific explanation when the SQLite
      document store is unreadable, Neo4j is unreachable, the Query Rewriter or
      Chat Agent deployment is unreachable, or CalMatters coverage cannot be
      loaded and refreshed.
- [ ] Dense embedding, structural construction, and branch-specific index
      availability do not gate startup; their failures retain the retrieval
      contract's branch-level behavior.
- [ ] One authored CalMatters Coverage Description is loaded at startup and its
      measured article count and date range are refreshed from current data.
- [ ] CalMatters is supplied as relevant to every version-one question, and no
      monthly coverage is supplied.
- [ ] The first ordinary message for a new browser conversation creates exactly
      one in-memory Chat Session and invokes its preparation operation.
- [ ] An awaiting-approval outcome exposes only the public Query Approval. The
      internal relational route is not emitted to the browser.
- [ ] Deferred coverage and its recoverable portion are shown with an otherwise
      approvable proposal.
- [ ] Declined and unavailable-rewrite outcomes are presented without offering
      approval or starting retrieval.
- [ ] The browser exposes neither a model picker nor optional tool controls.
- [ ] ASGI-level tests drive the preparation outcomes with a deterministic Chat
      Session factory and assert protocol events rather than frontend markup or
      private adapter state.

## Blocked by

- [01 — Launch the secured local chat shell](01-launch-secured-local-chat-shell.md).
