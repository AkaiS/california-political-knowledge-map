# Decide the developer retrieval surface

Labels: wayfinder:grilling, completed
Parent: [Useful Graph Retrieval](../MAP.md)
Blocked by: [Define the retrieval and answer contract](08-retrieval-and-answer-contract.md)

## Question

How does the first consumer — a developer investigating California politics —
actually ask questions and read answers?

Decide the shape: a `ca-map` subcommand alongside the existing CLI, an
interactive session in the manner of the Influence Graph Playground, or a
notebook-facing API. Settle how evidence and citations are presented in a
terminal, and how a developer inspects why a given answer was supported the way
it was, since a discovery layer is only useful if its support can be checked.

The constraint is that the surface stays a thin rendering of the retrieval and
answer contract. Any behaviour it needs that the contract does not express is a
gap in the contract, not something the surface should implement for itself —
otherwise the chat UI that replaces it later cannot inherit the same behaviour.

## Decisions settled during grilling

- The first interface is a local, single-user browser chat for a maintainer. It
  does not introduce hosting, authentication, accounts, or multi-user isolation.
- One Chat Session covers one political question. It may include Query
  Rewrite rejection, correction, and approval before retrieval, but a new
  political question starts a new conversation and does not depend on an earlier
  answer.
- The browser reuses Pydantic AI's stock chat frontend where practical, but the
  landed `ChatSession` remains the composition boundary. A thin deterministic web
  adapter maps browser conversations to in-memory Chat Sessions and drives
  `prepare()`, `reject(correction)`, and `approve()`; the core is not redesigned
  into model-callable tools merely to fit `Agent.to_web()`.
- A local FastAPI application is the composition boundary. It serves the stock
  frontend, owns the in-memory Chat Session registry and dependency lifecycle,
  translates browser requests into the deterministic adapter calls, and streams
  protocol events back to the browser.
- Version one does not change `ChatSession.approve()` to stream model tokens. The
  adapter marks `Search details` as running after approval, then emits the
  completed typed answer and safe inspection value together.
- Application startup fails when the SQLite document store is unreadable, Neo4j
  is unreachable, the Query Rewriter or Chat Agent deployment is unreachable, or
  the CalMatters Coverage Description cannot be loaded and refreshed. Dense and
  structural dependencies and branch-specific indexes retain the retrieval
  contract's partial-failure behavior and do not gate startup.
- `ca-map chat` starts the application on `127.0.0.1:7932`, prints the URL, and
  does not open the browser. It accepts `--port` but no version-one `--host`
  option, preserving the local-only trust boundary.
- The application uses Pydantic AI's default CDN-hosted frontend build and local
  cache. Version one does not vendor the offline frontend artifact, so its first
  launch may require network access.
- Query Rewrite approval presents only the public `QueryApproval`; the Chat
  Session retains the internal route. The person may approve it or reject it and
  supply a correction for the Query Rewriter to consider in another Query Rewrite
  Proposal.
- Correction is a two-step stock-UI interaction: reject the proposal, then send
  the requested change as the next chat message. The adapter waits for that
  message before calling the core's atomic `reject(correction)`. The correction
  returns to the Query Rewriter and cannot become an approved query without
  another proposal.
- Pending proposals live only in process memory. Restarting the local server
  invalidates an unfinished approval, while the stock UI retains completed
  Chat Sessions in browser storage. The application adds no durable
  pending-session or server-side transcript store.
- The registry removes a Chat Session after an answer, decline, or unrecoverable
  rewrite failure. A rejected proposal remains until the next message supplies
  its correction. A later message in a completed chat receives a deterministic
  instruction to start a new chat, without a model call. After server restart,
  browser history remains readable but cannot reconstruct or continue a Chat
  Session. Version one adds no expiry or background cleanup.
- The main Retrieval Answer uses numbered source links and verified passages.
  A dedicated safe serializer supplies the expandable inspection data, including
  retrieval routes, ranks, graph claims, coverage details, and branch outcomes;
  it does not expose unverified grounding text or detailed failure diagnostics.
  The adapter emits that value as a presentation-only `Search details` operation
  event so the stock frontend can use its collapsible tool-call component. The
  event is not a Chat Agent tool and is never exposed to the model.
- Version one supplies one authored CalMatters Coverage Description, refreshes
  its measured article counts and date range at startup, treats that collection
  as relevant to every question, and omits monthly coverage.
- Model Deployments remain startup configuration, and the browser offers no model
  picker or optional tool controls.
- This decision produces a ready-for-agent implementation PRD rather than adding
  the web application directly to the initiative ticket.

## Comments

2026-09-18: The decision was handed off through the Local Retrieval Chat PRD.
All five implementation issues and the parent project are complete, so this
initiative ticket is complete as well.
