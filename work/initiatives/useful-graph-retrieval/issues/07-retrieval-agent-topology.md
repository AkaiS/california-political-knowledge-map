# Decide the retrieval agent topology and orchestration

Labels: wayfinder:grilling, completed
Parent: [Useful Graph Retrieval](../MAP.md)
Inputs: [Accepted query construction and validation](05-prototype-query-construction-and-validation.md), [Accepted retrieval modes and index inventory](06-retrieval-modes-and-index-inventory.md)

## Question

What agent topology executes retrieval, and who decides that retrieval is
sufficient?

The modes inventory says what retrieval can do and the query-construction
decision supplies a typed semantic constructor with deterministic Cypher and
validation. Neither answers control flow.
Candidate topologies:

- A single agent holding the retrieval modes as tools, selecting among them.
- A Generator/Critic team loop with bounded query repair, extending the pattern
  already used by the Selector Healing Pipeline and the Coreference Critic.
- A planner that decomposes a question into several retrievals and composes the
  results.

Settle alongside it: what bounds the loop — hop budget, repair attempts, wall
clock, token spend — what happens when a bound is exhausted, and whether the
sufficiency judgement is made by a model or by a deterministic predicate over
retrieved evidence.

Whether this extends the repository's established Generator/Critic pattern or
departs from it should be stated as a decision rather than left for a PRD author
to infer.

This ticket blocks the contract deliberately: failure states such as a rejected
query after bounded repair, or an exhausted hop budget, are contract surface and
cannot be enumerated before the topology is known.

## Blocking

- Blocks: Define the retrieval and answer contract.

## Answer

Accepted during grilling on 2026-09-16. The topology is a user-approved Query
Rewrite followed by a fixed, graph-prioritized hybrid retrieval pipeline. It
does not use a retrieval planner, Generator/Critic team, post-retrieval model,
or sufficiency loop.

### Prepare and approve one Query Rewrite

The Chat Agent calls a separately configurable Query Rewriter whose Model
Deployment may be more capable than the deployments used by the downstream
semantic-schema filter and typed query selector. The rewriter produces one
natural-language question in the form of the 25 verified query-construction
cases. It makes requested entities, relationships, scope, dates or sessions,
and the result explicit. It omits separate requests for reporting or supporting
sources because every retrieval returns Grounding Evidence.

The Query Rewrite carries an internal `relational` boolean. The boolean controls
branch routing but is not shown to the user. Question policy and coverage
evaluate only the rewrite, and retrieval receives only the approved rewrite.
A Declined rewrite stops with an explanation. A Deferred rewrite explains the
current capability limit and any recoverable portion before the user approves
retrieval; the final answer repeats the relevant limitation.

The user sees and approves the rewritten question. Rejection records the
proposed question, its internal route, and any supplied correction, then permits
another rewrite. It is not a model failure. If the Query Rewriter exhausts
ordinary transport handling, retrieval does not fall back to the original
wording; the Chat Agent reports the network problem and says the query cannot be
answered at that time.

### Run a fixed concurrent retrieval pipeline

Every approved rewrite runs deterministic keyword extraction, full-text
retrieval, and dense Article Chunk retrieval. A Relational Question also runs
the typed structural constructor selected in issue 05 and preserved at
`511eaeee`. There is no other mode-selection agent. Enabled branches run
concurrently.

Typed structural retrieval permits at most three question-semantic relationship
hops, matching the deepest accepted target path. Fixed provenance and Grounding
Evidence hydration edges do not consume that budget. Each model-backed
construction stage gets its initial attempt and at most two corrections driven
by specific deterministic validation feedback.

One configurable wall-clock deadline covers the concurrent retrieval after
approval. The implementation PRD will choose its default from production-like
measurements rather than copy the prototype's per-call timeout. Completed
branches remain usable when another branch exhausts the deadline. There is no
independent run-wide token budget; fixed stage count, correction bounds, and
per-call limits bound usage, while total usage is recorded.

### Favor structural evidence without excluding text evidence

Weighted reciprocal-rank fusion combines the union of candidates and gives
typed structural retrieval greater weight than either full-text or dense
retrieval. Issue 09 chooses the numerical weights and candidate limits. A chunk
found only through a text branch remains eligible, and a chunk found through
several branches accumulates their contributions.

Every branch retains its candidate list before fusion and context truncation.
Each candidate retains Article Chunk identity, branch-local rank and score,
retrieval route and matched field, and any supporting graph claim. Raw scores
remain branch-local. Deduplication preserves every route and graph claim and
does not merge graph entities or resolve identity ambiguity.

### Assemble evidence without another model

A deterministic Evidence Assembler hydrates provenance, verifies displayed
wording against the original Story, groups passages by Source Article, attaches
the relevant Coverage Description, and applies the context budget. It does not
summarize, adjudicate, judge sufficiency, or request more retrieval.

The assembled package returns to the same Chat Agent that received the original
question. The Chat Agent produces the Retrieval Answer once. Proposing another
rewrite after retrieval is outside the initial scope.

### Retain branch facts and disclose failures

The retrieval result records expected branches, evidence recovered by each
branch, and failed branches instead of reducing them to `complete`, `partial`,
or another mandatory summary status. Consumers may synthesize such views without
the retrieval layer discarding diagnostic facts.

Every failed branch is disclosed. A structural failure on a Relational Question
is the prominent limitation; a full-text or dense failure remains visible but
secondary. A successful empty traversal says that no matching graph connections
were found in the available graph. Construction, validation, execution, or bound
failure says that those connections could not be searched.

Detailed failure location, kind, attempts consumed, and safe diagnostics belong
in logs rather than the answer contract. Structural logs distinguish schema
filtering, typed selection and wiring, binding, validation, hop-bound exhaustion,
Cypher execution, evidence hydration, and deadline exhaustion. Text-branch logs
retain their corresponding preparation, index, execution, and deadline stages.

This deliberately departs from the repository's Generator/Critic precedent.
Query construction already has deterministic validators, and fusion produces no
discrete model-authored artifact that would justify an independent critic.

Implementation is specified by the
[Graph-Prioritized Retrieval PRD](../../../projects/graph-prioritized-retrieval/PRD.md).
No ADR is added; the PRD is the feature's durable design document.

## Handoff

- Issue 08 defines typed evidence, citation, coverage, ranking, and answer
  representations around the granular execution facts fixed here: expected
  branches, branch evidence, and failed branches.
- Issue 09 tunes weighted reciprocal-rank fusion and candidate limits. It does
  not reopen whether structural retrieval receives greater weight.
- Issue 10 renders the Query Rewrite approval and resulting contract without
  adding retrieval behavior of its own.

## Input from the retrieval modes decision

[Issue 06](06-retrieval-modes-and-index-inventory.md) closed on 2026-09-08. The
available modes are full-text search over names, article titles, and chunk text;
Article Chunk vector search; and typed structural traversal. This ticket owns
which modes run, their order, and the sufficiency judgement. There is no accepted
rule requiring all three modes for every question.

Combine and deduplicate the chunks reached by whichever modes run, preserving
their retrieval routes and supporting graph claims. Combination is not another
mode, and issue 09 owns shared ranking. Source discovery does not require a
matching extracted relationship. Internal-ID lookup must preserve existing
identity ambiguity; external-identifier implementation and Policy Area vectors
are deferred.

## Input from the query-construction decision

[Issue 05](05-prototype-query-construction-and-validation.md) closed on
2026-09-14. Structural traversal uses the atomic semantic construction shape
preserved at `511eaeee`: models filter the semantic schema, select and wire typed
compiler-owned pieces, and bind positional question values. Code owns legal
graph shapes, validation, Cypher, Grounding Evidence traversal, Source Article
lookup, and result hydration. Bill-name bindings use the repository's Bill
Designation parser before entity resolution.

The constructor uses specific deterministic failures and bounded stage retries;
it does not add a general model critic. This ticket decides whether orchestration
needs a critic for cross-mode repair or sufficiency, plus the bounds and failure
states exposed to the answer contract.

## Comments

### 2026-09-14: Grilling, first round

The maintainer rejected general retrieval-mode selection. Retrieval normally
follows a fixed pipeline: query rewriting, keyword extraction, full-text retrieval,
dense retrieval, typed structural retrieval, and reciprocal-rank fusion with
greater weight for typed structural results. The fused result returns to the
Chat Agent that received the original question.

The possible exception is a zero-hop question, which may skip typed structural
traversal. The session has not yet settled the exact zero-hop criterion or who
classifies it. This exception means skipping relationship traversal, not
necessarily skipping Cypher as the database query language used to invoke other
retrieval capabilities.

The Chat Agent understands corpus coverage. It calls query rewriting first and
presents the rewritten query to the user. Retrieval begins only after the user
accepts that rewrite.

The remaining topology question is whether a model should inspect or package
the fused evidence before it returns to the Chat Agent. In particular, the
session must distinguish work that a model could add from deterministic result
hydration and grouping, and from reranking work already owned by issue 09.

### 2026-09-14: Grilling, second round

The maintainer chose a deterministic Evidence Assembler after ranking. It
hydrates provenance, groups passages by Source Article, supplies verified
original wording and relevant coverage limits, and applies the context budget
before returning a typed evidence package to the Chat Agent. No model summarizes,
curates, or judges the evidence between ranking and that return.

The maintainer wants typed structural retrieval to take priority while full-text
and dense retrieval fill gaps left by the graph. Weighted reciprocal-rank fusion
can express that policy without requiring a candidate to appear in the structural
result set. The precise weighting and gap-filling rule remain to be settled with
issue 09's empirical ownership kept explicit.

### 2026-09-14: Grilling, third round

The maintainer selected weighted reciprocal-rank fusion over the union of
candidates. Typed structural retrieval receives more weight than either
full-text or dense retrieval. Absence from the structural result set does not
exclude a candidate found by another route. Issue 09 will determine the actual
weights rather than reconsider whether structural retrieval receives priority.

Query rewriting uses a stronger model to restate the question as an explicit
brief for the weaker schema-filtering and query-selection models downstream. Its
typed output also carries a `relational` boolean for branch routing, but routing
is not the purpose of the rewrite. A non-relational question runs full-text and
dense retrieval. A Relational Question runs those two modes plus the typed
structural retrieval selected in issue 05. The Chat Agent presents the rewritten
question and this interpretation for user approval before retrieval begins.
Fixed provenance traversal and source hydration do not by themselves make a
question relational.

### 2026-09-14: Grilling, fourth round

There is no separate sufficiency gate after retrieval and no automatic retrieval
loop. Once every enabled branch has succeeded, failed, or exhausted its bound,
the Evidence Assembler returns the available evidence and coverage limits to the
Chat Agent. The Chat Agent answers the original question. Proposing another
rewritten query after retrieval is outside the current scope.

Enabled retrieval branches run concurrently. One failed branch does not discard
evidence returned by the others. The result retains the branch failure alongside
the successful evidence; the whole retrieval fails only if no enabled branch
completes successfully or the Evidence Assembler cannot produce a valid package.

A failed typed structural branch on a Relational Question is a prominent
relational-retrieval limitation, not an ordinary missing contribution to fusion.
The Chat Agent should explain that graph connections matching the question could
not be retrieved before presenting the most relevant full-text and dense
evidence. The contract must distinguish this execution or construction failure
from a successful structural traversal that found no matching graph connection.

If the user rejects the initial rewritten question or its `relational` value,
the Chat Agent supplies the correction to query rewriting and presents the new
typed rewrite for approval. It does not silently edit and execute a rejected
rewrite.

### 2026-09-15: Grilling, fifth round

Keyword extraction is deterministic and runs inside the retrieval pipeline
against the approved rewrite. It is not another model agent. Dense retrieval
uses the approved rewrite directly, while keyword extraction prepares the
full-text branch.

The Chat Agent reports both possible non-match and failure outcomes from typed
structural retrieval, using language that does not conflate them. A successful
empty traversal says that no matching graph connections were found in the
available graph. A construction, validation, execution, or bound failure says
that those connections could not be searched. Either outcome may accompany
full-text and dense evidence.

Every enabled retrieval-branch failure is disclosed when another branch still
returns evidence. A structural failure on a Relational Question remains the
prominent limitation; a full-text or dense failure is less prominent but cannot
be hidden in developer-only diagnostics. A successful empty result remains a
search outcome rather than a branch failure.

### 2026-09-16: Grilling, sixth round

Typed structural retrieval permits at most three question-semantic relationship
hops, covering the deepest path in the accepted target set. Fixed provenance and
Grounding Evidence hydration paths do not consume this budget.

Each model-backed construction stage gets an initial attempt and at most two
correction attempts driven by specific deterministic validation failures. When
that bound is exhausted, the structural branch reports the responsible
construction or validation failure. A user rejecting a rewritten question is
not a model correction and does not consume this budget.

One configurable wall-clock deadline covers the concurrent retrieval pipeline
after approval. The architecture does not freeze a duration copied from the
prototype; the implementation PRD will choose a default from production-like
latency measurements. When the deadline expires, completed branches remain
usable and unfinished branches report deadline exhaustion.

There is no independent run-wide token budget. Fixed model stages, their
correction bounds, and per-call input and output limits bound model usage. The
run still records total usage. A deployment-specific token ceiling may be added
later if measured cost or latency warrants it.

### 2026-09-16: Grilling, seventh round

The Query Rewriter is a planning stage, not a thin normalizer or a classifier
whose main job is setting `relational`. Its stronger model frames the user's
request so the weaker semantic-schema filter and typed query selector can
understand the requested entities, relationships, constraints, and result.

The maintainer reopened the placement of the question-policy check. Evaluating
the rewritten form may expose a disallowed framing that would otherwise leak
through the original wording. The session still needs to decide whether policy
checks the original question, the rewrite, or both, and which representation the
downstream construction stages receive.

### 2026-09-16: Grilling, eighth round

The Query Rewrite is one natural-language question shaped like the 25 verified
query-construction cases. It makes entities, relationships, sessions or dates,
and the requested result explicit. It omits separate requests for reporting or
supporting sources because every retrieval returns Grounding Evidence. A
`relational` boolean accompanies the question but does not turn the question
itself into a typed structural plan.

Question policy evaluates only the Query Rewrite. That is the question the user
approves and the retrieval pipeline executes, so a different original framing
cannot cause retrieval behavior that survived only outside the policy check.
The schema filter, typed query selector, keyword extractor, dense retriever, and
any other retrieval stage receive only the approved Query Rewrite, not the
original wording.

Semantic dissatisfaction with a rewrite is not a pipeline failure. The user
rejects it and the Chat Agent asks the Query Rewriter for another formulation
using that feedback. Transport failure, truncation, or failure to return the
minimal question-plus-boolean wrapper remain ordinary model-tool failures; they
prevent retrieval from starting but do not create a special semantic
query-rewrite failure or repair loop.

### 2026-09-16: Grilling, ninth round

The Query Rewriter uses a separately configurable Model Deployment that may be
more capable than the deployments used by the downstream semantic-schema filter
and typed query selector. The architecture fixes that role separation without
hard-coding a particular model.

After rewriting, the Chat Agent evaluates only the Query Rewrite against question
policy and coverage. A Declined question stops with an explanation. A Deferred
question is explained and may continue so retrieval can return partial evidence.
For a question that may proceed, the user sees and approves the rewritten
question only. The `relational` boolean is internal routing metadata and is not
part of the approval presentation.

If the Query Rewriter exhausts ordinary transport handling, retrieval does not
fall back to the original question. The Chat Agent reports the network problem
and says that it cannot answer the query at that time. User rejection remains a
request for another rewrite, not a technical failure.

### 2026-09-16: Grilling, tenth round

The retrieval contract must retain granular execution facts rather than reduce
them to `complete`, `partial`, or similar top-level states. It records which
branches were expected from the approved Query Rewrite, which branch recovered
which evidence, and which branches failed with their specific failure details.
Consumers may synthesize a summary from those facts, but the retrieval layer
does not discard the distinctions needed to diagnose a weak or failed result.

Query preparation retains `rewrite_unavailable` and also records
`rewrite_rejected` when the user asks for another formulation. Rejection is an
interaction outcome and may be followed by another rewrite; it is not a model
or retrieval failure.

When the approved Query Rewrite is Deferred, the Chat Agent explains the current
capability limit before asking for approval and identifies any portion that may
still be recoverable. If the user proceeds, the final answer repeats the relevant
limit alongside the evidence actually recovered.

### 2026-09-16: Grilling, eleventh round

Each retrieval branch retains its ranked candidate list before reciprocal-rank
fusion and Evidence Assembly. Every candidate retains its Article Chunk identity,
branch-local rank and score, retrieval route and matched field, and any supporting
graph claim. Fused candidates retain all contributing branch routes. A raw score
is meaningful only within the branch that produced it.

The retrieval result records expected branches, evidence recovered by each
branch, and which branches failed. User-facing output discloses every failed
branch according to the prominence rules above. Detailed failure location,
failure kind, attempts consumed, and safe diagnostics are logs rather than
answer-contract payload. Structural logs distinguish schema filtering, typed
selection and wiring, binding, validation, hop-bound exhaustion, Cypher
execution, evidence hydration, and deadline exhaustion; text branches record
their corresponding preparation, index, execution, and deadline stages.

Each `rewrite_rejected` record retains the proposed question, its internal
`relational` value, the rejection, and any correction the user supplied. Rejected
rewrites remain outside the retrieval pipeline. Only the approved Query Rewrite
becomes input to keyword extraction, dense retrieval, and, when relational,
typed structural retrieval.
