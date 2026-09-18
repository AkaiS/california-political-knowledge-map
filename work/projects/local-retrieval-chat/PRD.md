# Product Requirements: Local Retrieval Chat

Labels: completed

Parent: [Useful Graph Retrieval issue 10](../../initiatives/useful-graph-retrieval/issues/10-developer-retrieval-surface.md)

## Problem Statement

A maintainer can now drive an approved Query Rewrite through hybrid retrieval and
receive a typed Retrieval Answer, but doing so requires assembling Python objects
and calling the retrieval code directly. That makes an otherwise complete
retrieval path awkward to use for ordinary political questions and difficult to
inspect interactively.

The first usable interface should feel like a small chat, not like a developer
API or a collection of command flags. It must still preserve the system's
existing safeguards: the person sees and approves the proposed interpretation,
corrections return to the Query Rewriter, only verified Grounding Evidence is
presented as support, and partial retrieval remains visible. The interface must
not invent a second orchestration model or hide operational detail inside the
Chat Agent.

This is a local maintainer tool, not a hosted product. Adding accounts,
authentication, durable conversations, generalized collection discovery, or a
custom frontend would increase the implementation surface without answering the
immediate question: can a maintainer ask one California political question in a
browser and understand the resulting evidence?

## Solution

Add a local FastAPI application that serves Pydantic AI's stock web chat
frontend and adapts its conversation protocol to the existing deterministic
`ChatSession`. One browser conversation maps to one in-memory Chat Session and
one political question. The first message creates the Chat Session and asks it
to prepare a Query Rewrite Proposal. The browser presents only the public
Query Approval, never its internal route.

The person may approve the proposal or reject it. Rejection changes the
interaction into an awaiting-correction state; the next composer message is the
requested change. The adapter then records the rejection and correction
atomically through the existing Chat Session and requests another proposal.
Only a separately approved proposal can enter retrieval.

After approval, the browser shows a presentation-only `Search details`
operation as running. Version one waits for the existing non-streaming approval
call to finish, then emits the completed Retrieval Answer and safe inspection
details. The main answer contains numbered Source Article links and verified
passages. The expandable details contain routes, ranks, graph claims, relevant
coverage, and branch outcomes, while excluding unverified text and detailed
failure diagnostics.

The command `ca-map chat` starts the application on the loopback interface,
prints its URL, and leaves browser opening to the maintainer. Dependencies and
the single CalMatters Coverage Description are assembled once at startup.
Chat Sessions and pending approvals exist only in process memory; completed
frontend history remains in browser storage but cannot reconstruct server state
after a restart.

## User Stories

1. As a maintainer, I want to launch retrieval chat with one command, so that I
   can ask a political question without writing Python.
2. As a maintainer, I want the command to print the local URL, so that I can open
   the interface in the browser of my choice.
3. As a maintainer, I want the service bound to the loopback interface, so that
   a local tool is not accidentally exposed to my network.
4. As a maintainer, I want a stable default port, so that repeated launches are
   predictable.
5. As a maintainer, I want to override the port, so that I can avoid a local port
   conflict without changing configuration.
6. As a maintainer, I want the familiar Pydantic AI chat interface, so that the
   first retrieval surface does not require a custom frontend.
7. As a person asking about California politics, I want to enter my question in
   an ordinary chat composer, so that I do not need to know the graph ontology or
   retrieval API.
8. As a person asking a question, I want the system to show its proposed
   restatement before searching, so that I can catch a misunderstood request.
9. As a person reviewing a Query Rewrite Proposal, I want to see only the
   proposed question, so that internal routing does not distract from the intent
   I am approving.
10. As a person satisfied with the proposal, I want to approve it directly, so
    that retrieval starts without asking me to repeat the question.
11. As a person dissatisfied with the proposal, I want to reject it, so that an
    incorrect interpretation never reaches retrieval.
12. As a person who rejected a proposal, I want my next message treated as a
    correction, so that I can describe the specific change in my own words.
13. As a person supplying a correction, I want the Query Rewriter to consider
    it and return another proposal, so that my correction is not silently treated
    as the approved question.
14. As a person supplying a correction, I want to approve the revised proposal
    separately, so that every search is based on an explicitly accepted Query
    Rewrite.
15. As a person asking a Declined question, I want the policy explanation
    presented without retrieval, so that a refusal is not confused with an empty
    search.
16. As a person asking a Deferred question, I want the coverage limit and
    recoverable portion presented with the proposal, so that I can decide whether
    partial evidence is useful.
17. As a person encountering an unavailable Query Rewriter, I want a terminal
    failure message, so that my original wording is not searched without
    approval.
18. As a person who approved a proposal, I want visible feedback that the search
    is running, so that the non-streaming wait does not look like an ignored
    action.
19. As a person reading a Retrieval Answer, I want numbered Source Article links,
    so that each source is easy to open and reference.
20. As a person reading a Retrieval Answer, I want the supporting verified
    passages shown with their sources, so that I can check the answer against the
    reporting.
21. As a person reading a Retrieval Answer, I want retrieval limitations and
    branch failures kept visible, so that a partial search does not look
    complete.
22. As a maintainer inspecting an answer, I want expandable Search details, so
    that diagnostic information is available without overwhelming the main
    response.
23. As a maintainer inspecting Search details, I want to see retrieval routes and
    pre-fusion ranks, so that I can understand how a passage became a candidate.
24. As a maintainer inspecting Search details, I want to see supporting graph
    claims, so that I can distinguish structural support from text-only matches.
25. As a maintainer inspecting Search details, I want to see relevant coverage
    and branch outcomes, so that I can interpret missing evidence responsibly.
26. As a person reading Search details, I want unverified grounding text omitted,
    so that diagnostic candidates are not mistaken for verified quotations.
27. As a person reading Search details, I want internal failure diagnostics
    omitted, so that implementation and infrastructure details remain in logs.
28. As a person who has received an answer, I want a later message in the same
    browser conversation to tell me to start a new chat, so that a second
    political question cannot inherit hidden context.
29. As a person asking another political question, I want to start a new browser
    conversation, so that each Chat Session has one clear approved intent.
30. As a maintainer, I want completed conversations to remain readable in browser
    history, so that I can revisit an answer during the same local workflow.
31. As a maintainer returning after a server restart, I want old history to stay
    readable but continuation to fail clearly, so that browser state is not
    mistaken for a live Chat Session.
32. As a maintainer, I want pending approvals invalidated by a restart, so that
    the application does not pretend it durably saved state it never persisted.
33. As a maintainer, I want abandoned awaiting-correction conversations to cost
    only their in-memory entry, so that version one needs no expiry worker or
    cleanup subsystem.
34. As a maintainer, I want terminal Chat Sessions removed from the server
    registry, so that completed, declined, and irrecoverably failed work does not
    accumulate in memory.
35. As an operator, I want startup to fail when the document store, Neo4j, the
    Query Rewriter, the Chat Agent, or coverage cannot support any useful chat,
    so that the browser is not served in a fundamentally broken state.
36. As an operator, I want dense, structural, and branch-index failures to retain
    the retrieval contract's partial-failure behavior, so that one unavailable
    branch does not prevent text evidence from being useful.
37. As an operator, I want Model Deployments fixed at startup, so that the browser
    does not introduce an unreviewed model-selection surface.
38. As a maintainer, I want the application to use one authored CalMatters
    Coverage Description, so that coverage claims are intentional rather than
    inferred from whichever records happen to be retrieved.
39. As a maintainer, I want measured CalMatters article counts and date range
    refreshed at startup, so that the authored description contains current
    inventory facts.
40. As a person asking a question, I want CalMatters treated as relevant to every
    version-one question, so that I can use the current single collection without
    a collection-selection workflow.
41. As a developer, I want the existing Chat Session to remain the orchestration
    boundary, so that adding a browser does not duplicate question preparation or
    retrieval behavior.
42. As a developer, I want browser protocol handling to be deterministic, so that
    model behavior cannot reinterpret approvals, corrections, or session
    lifecycle events.
43. As a developer, I want Search details to be presentation-only, so that a UI
    convenience does not become a model-callable tool.
44. As a developer, I want the adapter to render the existing typed outcomes, so
    that the interface does not create a second retrieval or answer contract.
45. As a developer, I want the final answer emitted only after approval completes,
    so that version one does not require changing the core to stream model tokens.
46. As a maintainer, I want the stock frontend downloaded and cached through
    Pydantic AI, so that the project does not vendor a large frontend artifact.
47. As a maintainer launching the UI for the first time, I want its possible
    network requirement documented, so that a CDN fetch is not mistaken for an
    application failure.

## Implementation Decisions

### Application boundary

- Build one local FastAPI application as the composition boundary for the
  browser interface. It owns dependency startup and shutdown, coverage loading,
  the in-memory Chat Session registry, browser-protocol translation, and response
  event emission.
- Reuse Pydantic AI's stock web chat frontend and its supported conversation
  protocol where practical. Do not build a custom JavaScript application for
  version one.
- Use Pydantic AI's default CDN-hosted frontend build and local cache. Do not
  vendor the offline frontend artifact. A first launch may require network
  access.
- Upgrade Pydantic AI to version 2.30.0 or later before exposing its frontend so
  the stock web application validates the Host header against DNS rebinding,
  even though this application binds only to loopback.
- Keep the existing deterministic Chat Session as the feature's core composition
  boundary. Do not remodel its operations as Chat Agent tools merely to fit the
  stock frontend.
- Introduce a thin deterministic adapter that maps the frontend conversation ID
  to one in-memory Chat Session and translates messages, approvals, rejections,
  and output into supported protocol events.

### Chat Session interaction

- One Chat Session covers exactly one political question. Rewrite rejection,
  correction, another proposal, approval, retrieval, and the final answer remain
  part of that same Chat Session.
- The first ordinary user message creates a Chat Session and invokes question
  preparation. No Chat Session exists before the first political question.
- Present only the public Query Approval from a Query Rewrite Proposal. The
  internal relational route remains inside the existing core types.
- Approval invokes the existing approval operation once. A consumed approval
  cannot be repeated.
- Rejection is a two-step stock-UI interaction. Rejecting a proposal moves the
  adapter to awaiting correction. The next ordinary composer message is the
  correction; only then does the adapter call the core's atomic rejection with
  that correction and prepare another proposal.
- A correction never becomes an approved Query Rewrite directly. Retrieval can
  begin only after the resulting proposal receives its own approval.
- Declined questions, unavailable rewrites, completed answers, and unrecoverable
  answer failures are terminal for that Chat Session.
- A later message addressed to a terminal conversation receives a deterministic
  instruction to start a new chat. It does not invoke a model or construct a new
  Chat Session under the old conversation ID.

### State and lifecycle

- Keep Chat Sessions and pending approvals in a process-local registry. Add no
  server-side transcript store or durable pending-session representation.
- Remove a registry entry after an answer, a Declined outcome, an unavailable
  rewrite, or another unrecoverable terminal failure.
- Keep a rejected proposal's entry while it awaits the next correction message.
- Add no expiry, background cleanup, or abandoned-session recovery in version
  one. An abandoned nonterminal entry lasts until process exit.
- Browser-managed history may remain readable after process exit. A restarted
  application does not reconstruct or continue a Chat Session from frontend
  history.
- The application is single-user and local. The registry is not an account,
  authentication, authorization, or multi-tenant isolation mechanism.

### Retrieval Answer presentation

- Render the main Retrieval Answer with numbered Source Article links and the
  verified passages selected by Evidence Assembly. Preserve all existing
  Deferred and partial-failure disclosures.
- Add one dedicated safe serializer for expandable inspection data. Its output
  includes retrieval routes, branch-local ranks, supporting graph claims,
  relevant Coverage Description facts, and branch outcomes.
- The safe serializer must not include unverified grounding text or detailed
  failure diagnostics. Those diagnostics remain available through existing
  logging.
- Emit the safe value as a presentation-only `Search details` operation event so
  the stock frontend renders it through its collapsible operation component. It
  is not a Chat Agent tool and is never included in model context.
- Version one does not stream final model tokens. Immediately after approval,
  emit Search details in a running state. When the existing approval operation
  returns, emit the completed operation value and completed typed answer.

### Startup and dependencies

- Assemble the Query Rewriter, Chat Agent, Retrieval Coordinator, database
  adapters, Model Deployments, and coverage once during application startup and
  release owned resources during shutdown.
- Fail startup when the SQLite document store is unreadable, Neo4j is
  unreachable, the configured Query Rewriter or Chat Agent deployment is
  unreachable, or the CalMatters Coverage Description cannot be loaded and
  refreshed. Each failure should identify the unavailable dependency without
  serving a misleadingly healthy chat surface.
- Do not gate startup on dense embedding, structural construction, or
  branch-specific index availability. Those failures retain the existing
  branch-level partial-failure and disclosure contract.
- Supply one authored CalMatters Coverage Description. Refresh measured article
  counts and date range from the current data at startup, use the CalMatters
  collection as relevant for every version-one question, and provide no monthly
  coverage.
- Keep Model Deployments as startup configuration. The frontend has no model
  picker and no optional tool controls.

### Command

- Add `ca-map chat` to the existing command surface.
- Bind Uvicorn to `127.0.0.1` on port `7932` by default. Support only a `--port`
  override in version one; do not add a `--host` option.
- Print the browser URL after launch begins. Do not open a browser automatically.
- Keep the command in the foreground and let normal process termination drive
  FastAPI shutdown and resource cleanup.

## Testing Decisions

A good test observes behavior at the highest boundary that owns the behavior.
It asserts the protocol events and user-visible outcomes produced for a browser
conversation, not internal registry layout, prompt text, frontend HTML, private
method calls, or Pydantic AI implementation details.

The primary seam is the FastAPI application exercised as an ASGI client with an
injected Chat Session factory and startup dependencies. This single seam should
cover the interaction state machine and rendering contract:

- The first question creates one Chat Session and returns its public Query
  Approval without its internal route.
- Approval emits a running Search details operation, calls approval once, and
  returns the numbered answer, verified passages, disclosures, and completed
  safe details.
- Rejection waits for a correction message, passes that correction atomically to
  the Chat Session, and returns a new proposal that still requires approval.
- Declined and unavailable-rewrite outcomes terminate without retrieval.
- A later message in a terminal conversation receives the deterministic
  start-a-new-chat response without another model call.
- Nonterminal sessions remain isolated by conversation ID, and a new application
  instance cannot resume browser-only history.
- Search details include routes, ranks, graph claims, coverage, and branch
  outcomes while excluding unverified text and internal failure diagnostics.
- Startup succeeds or fails according to the agreed dependency boundary, while
  branch-only dependency failures do not become startup gates.

Use deterministic fakes that return the same public Pydantic outcome types as
the real Chat Session. Do not duplicate question preparation or retrieval logic
inside the fakes. Prior art is the existing Chat Session suite, which drives
scripted Pydantic AI models and fake retrieval dependencies, and the retrieval
coordinator suite, which asserts typed branch outcomes without live services.

The only additional seam is the existing command dispatcher. Invoke it with
argument lists and replace the Uvicorn runner with a recorder. Assert the default
loopback address and port, the `--port` override, printed URL, absence of a
`--host` option, and that browser opening is never requested. Prior art is the
existing command suite, which invokes the command entry point directly and
replaces its external handlers.

Do not add browser automation or snapshot tests. The stock frontend owns its own
visual behavior; this project owns only the supported protocol events supplied
to it. Do not require live Neo4j, SQLite, CDN, or model deployments in the
deterministic test suite. Existing integration tests continue to own the real
retrieval adapters and Chat Session behavior behind the application seam.

## Out of Scope

- Hosting the application or binding it to a non-loopback interface.
- Authentication, user accounts, authorization, multi-user concurrency
  guarantees, or tenant isolation.
- More than one political question in a Chat Session or conversational context
  carried between answers.
- A custom frontend, custom chat design system, or vendored offline frontend
  bundle.
- Automatically opening a browser.
- Server-side transcripts, durable Chat Sessions, persisted pending approvals,
  or reconstruction from frontend history after restart.
- Session expiry, time-to-live configuration, abandoned-session cleanup, or a
  background janitor.
- Streaming final Chat Agent tokens or changing the core approval operation to
  stream.
- A model picker, tool picker, user-editable deployment settings, or runtime
  provider switching.
- General collection discovery, collection selection, multiple authored
  Coverage Descriptions, or monthly coverage.
- New retrieval behavior, another answering agent, a sufficiency loop, or a
  redesign of the existing retrieval and answer contracts.
- Presenting unverified candidate text or detailed infrastructure diagnostics in
  the browser.
- Automated browser testing of Pydantic AI's stock frontend.

## Further Notes

- This PRD is the implementation handoff from Useful Graph Retrieval issue 10.
  It specifies a thin consumer of the completed Graph-Prioritized Retrieval
  project rather than reopening that project's retrieval decisions.
- The default CDN frontend behavior deliberately trades first-launch offline use
  for a much smaller local implementation. If offline operation becomes a real
  requirement, it should be justified by observed use rather than included
  preemptively.
- The local-only boundary reduces exposure but does not make known dependency
  vulnerabilities acceptable; the Pydantic AI upgrade is part of enabling the
  web surface.
- No ADR is required. The FastAPI adapter, stock frontend, process-local state,
  and launcher choices are local, unsurprising, and reversible. This PRD is the
  durable design record.
