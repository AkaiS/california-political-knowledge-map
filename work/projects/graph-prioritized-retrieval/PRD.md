# Product Requirements: Graph-Prioritized Retrieval

Labels: ready-for-agent

Parent: [Useful Graph Retrieval issue 07](../../initiatives/useful-graph-retrieval/issues/07-retrieval-agent-topology.md)

## Problem Statement

A person asking about California politics should not have to know the graph
ontology, write Cypher, or guess which retrieval method fits the question. The
system must translate ordinary wording into the concise question form its
retrieval models understand, show that interpretation to the person, and search
only after they approve it.

The retrieval layer also has two competing obligations. Typed graph traversal
should receive priority because relationships are the point of maintaining the
graph. At the same time, the graph is incomplete. Missing relationships,
unresolved identities, and absent claim properties must not hide relevant
reporting that full-text or dense retrieval can still find.

The selected typed structural constructor is also model-assisted. Its schema
filter and query selector may fail even when full-text and dense retrieval work.
A single success label would conceal whether the rewriter, one retrieval branch,
fusion, or evidence hydration caused a weak result. The system needs a bounded,
inspectable pipeline that returns useful partial evidence without presenting a
failed search as a complete one.

## Solution

Add a user-approved Query Rewrite before retrieval. A separately configurable,
more capable model restates the request in the same concise form as the 25
verified query-construction cases. It makes the entities, relationships, scope,
and requested result explicit, while omitting a separate request for reporting
because every retrieval returns Grounding Evidence. The rewrite also carries an
internal `relational` boolean.

The Chat Agent evaluates only the Query Rewrite against question policy and the
Coverage Description. It explains Declined and Deferred capability boundaries,
then shows an allowed rewrite to the user. A rejected rewrite returns to the
rewriter with the user's correction. Only an approved rewrite enters retrieval.

Retrieval is a fixed hybrid pipeline. Every approved question runs deterministic
keyword extraction, full-text retrieval, and Article Chunk dense retrieval. A
Relational Question also runs the typed structural constructor selected by the
prototype at `511eaeee`. Enabled branches run concurrently under one deadline.
The structural branch permits at most three question-semantic relationship hops
and two corrections after each model-backed construction stage's initial
attempt.

Weighted reciprocal-rank fusion combines the union of branch candidates and
gives structural retrieval greater weight than either text branch. Dense and
full-text candidates remain eligible when the graph lacks a route. A
deterministic Evidence Assembler then hydrates provenance, verifies original
wording, groups passages by Source Article, attaches relevant coverage limits,
and applies the context budget before returning the evidence package to the
original Chat Agent.

There is no post-retrieval model, critic, or sufficiency loop. The pipeline
records expected branches, evidence recovered by each branch, and failed
branches. Candidate routes and pre-fusion ranks remain inspectable. Detailed
failure stages and attempts go to logs, while user-facing output discloses every
failed branch and distinguishes an empty successful traversal from failure to
perform the traversal.

## User Stories

1. As a person asking about California politics, I want the system to restate my
   question before searching, so that I can correct a misunderstood request.
2. As a person asking about California politics, I want the rewrite to preserve
   the named people, organizations, measures, dates, and sessions in my question,
   so that retrieval answers the question I intended.
3. As a person asking about California politics, I want the rewrite to omit
   redundant requests for reporting, so that downstream models receive the
   concise question form they were evaluated against.
4. As a person asking about California politics, I want to approve only the
   rewritten question, so that internal routing details do not leak into the
   conversation.
5. As a person who rejects a rewrite, I want my correction used in the next
   rewrite attempt, so that I do not have to restate the entire request.
6. As a person asking an unsupported question, I want the current capability
   limit explained before retrieval, so that I know what the system cannot
   establish.
7. As a person asking a Deferred question, I want the recoverable portion named
   before I approve retrieval, so that I can decide whether partial evidence is
   useful.
8. As a person asking a Declined question, I want an explanation instead of an
   irrelevant search, so that the system does not pretend the refusal was a
   retrieval failure.
9. As a person asking an entity or source-discovery question, I want full-text
   and dense retrieval without unnecessary structural construction, so that a
   simple search does not pay for a graph plan it does not need.
10. As a person asking a Relational Question, I want full-text, dense, and typed
    structural retrieval, so that graph relationships receive priority without
    excluding relevant reporting.
11. As a person asking a Relational Question, I want graph-backed results ranked
    more highly when available, so that the graph contributes more than another
    undifferentiated candidate list.
12. As a person asking about a relationship missing from the graph, I want dense
    and full-text evidence to remain eligible, so that extraction gaps do not
    hide relevant sources.
13. As a person reading an answer, I want every selected passage tied to its
    Source Article, so that I can inspect the original reporting.
14. As a person reading an answer, I want quoted wording verified against the
    original Story, so that transformed Article Chunk text is not presented as
    a verbatim quotation.
15. As a person reading a partial answer, I want every failed retrieval branch
    disclosed, so that a reduced search does not look complete.
16. As a person asking a Relational Question, I want structural failure stated
    prominently, so that text-only evidence is not mistaken for a completed graph
    search.
17. As a person asking a Relational Question, I want “no matching graph
    connection” distinguished from “the graph could not be searched,” so that I
    understand what the result actually establishes.
18. As a person facing a Query Rewriter network failure, I want a clear temporary
    failure message, so that the system does not silently search my original
    wording.
19. As a developer, I want the approved Query Rewrite to be the sole question
    supplied to retrieval, so that every downstream stage operates on the same
    user-approved intent.
20. As a developer, I want `relational` to be an internal boolean, so that branch
    routing is explicit without becoming a user-facing concept.
21. As a developer, I want deterministic keyword extraction, so that sparse
    retrieval does not add another model agent or retry loop.
22. As a developer, I want enabled branches to run concurrently, so that dense
    and full-text retrieval do not wait for structural construction.
23. As a developer, I want one retrieval deadline, so that the run reaches a
    terminal result even if one branch stalls.
24. As a developer, I want completed branches retained after another branch
    exhausts the deadline, so that recoverable evidence is not discarded.
25. As a developer, I want typed structural traversal capped at three semantic
    hops, so that it covers the accepted target set without enabling open-ended
    graph exploration.
26. As a developer, I want each model-backed construction stage limited to two
    corrections after its first attempt, so that deterministic feedback can fix
    bounded mistakes without creating an orchestration loop.
27. As a developer, I want provenance and evidence-hydration edges excluded from
    the semantic hop count, so that grounding does not consume question depth.
28. As a developer, I want the structural constructor to compile legal Cypher in
    code, so that no model writes free-form database queries.
29. As a developer, I want weighted reciprocal-rank fusion over the candidate
    union, so that candidates need not appear in every branch to remain eligible.
30. As a developer, I want branch-local scores kept branch-local, so that scores
    with incompatible scales are not compared as though they meant the same
    thing.
31. As a developer, I want every fused candidate to retain all retrieval routes,
    so that deduplication does not erase why the candidate was found.
32. As a developer, I want an Evidence Assembler rather than an answering model,
    so that packaging cannot introduce unsupported summaries between retrieval
    and the Chat Agent.
33. As an AI engineer, I want the Query Rewriter deployment configured
    independently from the weaker construction deployments, so that model choice
    reflects each role.
34. As an AI engineer, I want rejected rewrites retained with the internal route
    and user correction, so that rewrite quality can be evaluated later.
35. As an AI engineer, I want each branch's ranked candidates retained before
    fusion, so that I can tell a retrieval miss from a ranking cutoff.
36. As an operator, I want logs to identify the failing branch, stage, failure
    kind, and attempts consumed, so that I can locate the responsible component.
37. As an operator, I want structural logs to distinguish schema filtering,
    typed selection and wiring, binding, validation, hop bounds, Cypher execution,
    hydration, and deadline exhaustion, so that “structural failed” is not the
    only diagnosis available.
38. As an operator, I want text-branch logs to distinguish preparation, index,
    execution, and deadline failures, so that index outages and bad keyword
    preparation do not look alike.
39. As an operator, I want total model usage recorded without a separate
    run-wide token cutoff, so that cost is measurable without interrupting a
    valid structured response mid-stage.
40. As a maintainer, I want no automatic second retrieval after evidence returns,
    so that the approved query remains the only search performed.
41. As a maintainer, I want no Generator/Critic loop in retrieval, so that a
    critic is introduced only after evaluation identifies a discrete artifact
    it can judge better than deterministic validation.
42. As a maintainer, I want the contract to retain expected branches, recovered
    evidence, and failed branches instead of one summary status, so that later
    queries can synthesize the view they need without losing diagnostic facts.

## Implementation Decisions

### Query preparation

- Introduce a Query Rewriter as a model-backed component with its own Model
  Deployment setting. It may use a more capable deployment than the structural
  schema filter and typed query selector.
- A Query Rewrite contains one natural-language question and an internal
  `relational` boolean. The question itself is not a typed structural plan.
- The rewritten question follows the form of the 25 verified construction
  cases. It names the requested entities, relationships, dates or sessions, and
  result. It removes explicit requests for reporting or citations because
  Grounding Evidence is unconditional.
- Question policy and coverage evaluate only the Query Rewrite. The original
  wording is not passed to retrieval.
- The Chat Agent presents only the rewritten question. The internal routing
  boolean is not user-facing.
- A rejected rewrite records the proposal, its `relational` value, the rejection,
  and any user correction. The correction can drive another rewrite attempt.
- Query Rewriter transport exhaustion prevents retrieval. There is no fallback
  to the original wording. The Chat Agent reports a network problem and that the
  query cannot be answered at that time.
- A Declined rewrite stops before approval and retrieval. A Deferred rewrite
  names the current capability limit and recoverable portion before approval;
  the final answer repeats the relevant limit after retrieval.

### Retrieval routing and execution

- Every approved Query Rewrite runs deterministic keyword extraction, full-text
  retrieval, and dense Article Chunk retrieval.
- When `relational` is true, the run also includes typed structural retrieval.
  There is no other mode-selection agent or planner.
- Enabled branches start concurrently after approval and keyword preparation.
  One configurable wall-clock deadline covers the run.
- Deadline exhaustion does not discard completed branch evidence. Each unfinished
  branch is recorded as failed and disclosed to the user.
- The run has no independent total-token ceiling. Fixed stage count, correction
  limits, and per-call input and output limits bound usage. Total usage is logged.

### Retrieval branches

- Full-text retrieval covers entity names, Source Article titles, and Article
  Chunk text through the index inventory selected by the retrieval-modes
  decision. The contract calls this full-text retrieval rather than promising a
  particular ranking algorithm that Neo4j does not guarantee.
- Dense retrieval embeds the approved Query Rewrite and searches the existing
  Article Chunk vector index.
- Typed structural retrieval productionizes the atomic semantic construction
  shape preserved at `511eaeee`. Models filter the semantic schema, select and
  wire compiler-owned pieces, and bind values. Code owns legal shapes,
  validation, Cypher, execution, provenance traversal, Source Article lookup,
  and hydration.
- Structural retrieval permits at most three question-semantic relationship
  hops. Fixed provenance and Grounding Evidence hydration paths do not consume
  that budget.
- Each model-backed structural stage gets its initial response and at most two
  corrections driven by specific deterministic validation feedback.
- Bill-name values pass through the shared Bill Designation parser before entity
  resolution. Existing identity ambiguity remains visible.

### Candidate retention and fusion

- Each branch retains its ranked candidate list before fusion or context
  truncation. A candidate carries Article Chunk identity, branch-local rank and
  score, its retrieval route and matched field, and any supporting graph claim.
- Raw scores are meaningful only within their originating branch.
- Candidate combination deduplicates Article Chunks while preserving every
  contributing route and graph claim. It does not merge graph entities.
- Weighted reciprocal-rank fusion runs over the candidate union. Structural
  retrieval has greater weight than either full-text or dense retrieval. The
  reranking prototype selects the numerical weights and candidate limits.

### Evidence Assembly

- The Evidence Assembler is deterministic. It hydrates retained provenance,
  verifies any displayed quotation against the original Story body, groups
  passages by Source Article, attaches the relevant Coverage Description, and
  applies the context budget.
- The assembler does not summarize evidence, decide sufficiency, adjudicate
  disagreements, or start another retrieval.
- The completed evidence package returns to the same Chat Agent that received
  the original question. The Chat Agent produces the Retrieval Answer once.

### Outcomes and observability

- The retrieval result records expected branches, evidence recovered by each
  branch, and failed branches. It does not collapse those facts into `complete`,
  `partial`, or another mandatory top-level summary.
- A successful branch with no candidates is different from a failed branch. A
  successful empty structural traversal says no matching graph connections were
  found in the available graph. A failed structural branch says the graph
  connections could not be searched.
- Every failed branch is disclosed. Structural failure on a Relational Question
  is the prominent limitation; full-text and dense failures remain visible but
  secondary.
- Detailed failure location, kind, attempts, and safe diagnostics are logs, not
  answer-contract payload. Logs preserve enough detail to distinguish each model,
  compiler, database, index, hydration, and deadline stage.
- Query preparation records `rewrite_unavailable` and `rewrite_rejected`.
  Rejection is an interaction outcome, not a system failure.

### Dependencies and sequencing

- The retrieval and answer contract decision supplies the final typed evidence,
  citation, coverage, and branch-result representations.
- The graph-aware reranking prototype supplies weighted-RRF parameters and
  candidate limits. Structural priority itself is already decided.
- The developer retrieval surface renders this project's contracts but does not
  define new retrieval behavior.
- No ADR is added. This PRD is the feature's durable design document.

## Testing Decisions

A good test asserts externally visible behavior at the highest boundary that can
observe it. Tests should assert the approved Query Rewrite, enabled branches,
retained branch evidence, user-visible limitations, and assembled evidence
package. They should not assert prompt wording, task scheduling internals, or a
particular Cypher string when an equivalent compiled query satisfies the same
typed request.

Two seams cover the feature.

- **Question preparation seam.** Drive the Query Rewriter with a scripted model
  and a fake policy and coverage provider. Assert that output follows the
  verified-case question form, explicit reporting requests are removed,
  `relational` stays internal, policy reads only the rewrite, Declined and
  Deferred behavior differs, rejection retains feedback, and transport
  exhaustion never falls back to the original question. Prior art is the
  repository's existing Pydantic AI `FunctionModel` agent tests.
- **Approved-rewrite-to-evidence-package seam.** Inject fake full-text, dense,
  structural, fusion, coverage, original-story, and clock dependencies into the
  retrieval coordinator. Assert branch routing, concurrent completion under one
  deadline, survival of completed evidence after another branch fails, the
  three-hop and correction bounds, route-preserving fusion input, deterministic
  Evidence Assembly, and the distinction between structural emptiness and
  structural failure. Prior art is `StoryPipeline.run` tested through injected
  adapter protocols.

Focused integration tests remain at adapter boundaries where a fake would only
repeat the implementation:

- Full-text tests create the required indexes in a disposable Neo4j database and
  verify name, title, and chunk-text retrieval with branch-local scores.
- Dense tests exercise the Article Chunk vector index with deterministic
  embeddings and verify ranked candidate identities.
- Structural tests run the compiled read-only query against a controlled graph
  and verify nodes, graph claims, Grounding Evidence, Source Article hydration,
  Bill Designation handling, and the three-hop ceiling.
- Logging tests capture structured records and verify branch, stage, failure
  kind, attempt count, and deadline detail without asserting human prose.

The 25 verified query-construction cases remain development cases, not a Gold
Set. They test compatibility with the selected constructor and rewrite form.
Claims about retrieval quality require the Evaluation Data Set and Evaluation
Suite owned by the Model Evaluation initiative.

## Out of Scope

- Building a chat UI or choosing the developer-facing terminal rendering.
- Adding a post-retrieval answer agent, Evidence Curator, sufficiency critic, or
  automatic second retrieval.
- Free-form model-generated Cypher.
- Letting a model select among retrieval modes beyond the internal relational
  branch flag.
- Choosing weighted-RRF numbers or final candidate and context limits before the
  graph-aware reranking prototype reports them.
- Defining the final retrieval and answer schemas already owned by the retrieval
  and answer contract decision.
- Adding Policy Area vectors, external-identifier lookup, community detection,
  Graph Data Science, or influence ranking.
- Resolving duplicate graph identities or treating deduplication of candidates
  as Entity Resolution.
- Expanding the target set beyond three question-semantic relationship hops.
- Complete legislative, campaign-finance, district, tenure, redistricting, or
  event-time coverage.
- Retrieval caching or materialized query results.
- A run-wide token cutoff. Deployment-specific cost controls may be added after
  measurement establishes a need.
- A new ADR. The project implements the feature recorded here.

## Further Notes

This project deliberately does not extend the repository's Generator/Critic
pattern. Selector Healing and Coreference Resolution present critics with a
discrete artifact and a narrow verdict. Retrieval has deterministic validators,
three independent evidence branches, and no model-authored artifact after
fusion that warrants another model pass.

The current graph remains suitable for implementation and deterministic tests,
but it is not complete political coverage. Full-text and dense retrieval are
first-class branches precisely because missing graph structure must not exclude
relevant Grounding Evidence.
