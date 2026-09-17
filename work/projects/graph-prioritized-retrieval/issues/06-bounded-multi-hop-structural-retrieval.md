# 06 — Bounded multi-hop structural retrieval

Labels: completed

## Parent

[Graph-Prioritized Retrieval](../PRD.md)

## What to build

Extend typed structural retrieval across the accepted relational target set.
Questions may traverse at most three question-semantic relationships. Each
model-backed construction stage gets its initial response and no more than two
corrections driven by specific deterministic feedback.

## Acceptance criteria

- [x] Typed structural retrieval supports valid two-hop and three-hop questions
      from the verified construction cases.
- [x] Question-semantic traversal cannot exceed three relationships.
- [x] Fixed provenance, Source Article lookup, and Grounding Evidence hydration
      paths do not consume the semantic hop budget.
- [x] Each model-backed construction stage receives one initial attempt and at
      most two correction attempts.
- [x] Corrections receive the specific deterministic failure that rejected the
      preceding response.
- [x] Questions with several Bill-name slots use an explicit multi-value
      assignment contract and never bind one Bill Designation to every slot.
- [x] Exhausted schema filtering, selection and wiring, binding, validation,
      and hop bounds remain distinct structural failures.
- [x] A successful three-hop search with no candidates remains a successful
      empty result rather than a construction failure.
- [x] Controlled-graph tests cover two-hop and three-hop retrieval, correction
      success, correction exhaustion, the hop ceiling, multi-Bill binding, and
      provenance hydration beyond the semantic hop count.
- [x] The 25 verified construction cases remain runnable as development checks
      and are not described as a held-out Gold Set.

## Blocked by

- [05 — Typed structural retrieval to Grounding Evidence](05-typed-structural-retrieval.md).

## Comments

### Public test seams and implementation, 2026-09-17

The user's blanket confirmation covers the exact seams recorded in
[structural retrieval](../../../../docs/structural-retrieval.md) before tests:
`Neo4jStructuralRetriever.retrieve(request: RetrievalRequest, *, deadline:
float) -> SuccessfulBranch | FailedBranch` and
`get_structural_agents(*, ontology_model, selection_model, wiring_model,
binding_model) -> StructuralAgents`. Tests drive scripted model responses and
the external Neo4j boundary, then inspect candidates, graph claims, Grounding
Evidence, typed model requests, correction feedback, and structured logs.

The compiler now accepts connected questions with up to three semantic
relationship occurrences and four role occurrences. It validates every
endpoint and filter, rejects disconnected wiring, and supplies an explicit
different-entity constraint for same-side intersections. The compiler-owned
recorded-vote alternative searches aye, no, and abstained claims in one hop.
Hydration follows every matched claim and preserves the whole claim tuple on
each candidate. Chunk-level and article-level provenance use fixed paths
outside the semantic hop budget.

The accepted reported-alongside family is a zero-semantic-hop construction:
two entity roles share one Article Chunk through compiler-owned `MENTIONED_IN`
paths, with an optional Source Article title applied through `HAS_CHUNK`. The
requested entity is retained as the route entry node, while those fixed paths
remain provenance rather than invented semantic claims.

Pydantic AI output validators supply deterministic `ModelRetry` feedback and
allow at most two corrections for each stage. Pydantic shape failures share
that budget. Exhaustion retains the responsible stage and attempts consumed;
the hop ceiling has its own failure stage. All attempts use the original
deadline and contribute to model usage. A later database failure counts its
own attempt rather than inheriting the binder's corrections.

Multiple Bill-name slots require an explicit slot-to-value assignment. Each
value passes through the shared Bill Designation parser. Missing assignments,
duplicate slots, positional ambiguity, and repeated normalized Bill identities
are rejected; explicit differing sessions can distinguish a repeated bill
number. No first-designation fallback copies a question's first Bill across
the slots.

Red-green slices established two-hop hydration, correction feedback, hop-bound
failure classification, explicit multi-Bill assignment, exclusion of the seed
in a same-side intersection, stage-local attempt accounting, and the recorded
vote alternatives. Additional controlled cases cover three-hop success and
emptiness, article-level provenance, and both correction opportunities plus
exhaustion at every model stage.

Verification passed:

- Focused structural tests: 71 passed, including 35 disposable-Neo4j cases.
- One final full deterministic suite: 1084 passed, 45 opt-in integration tests
  skipped, and the same two existing provider warnings.
- Changed-module `uvx --offline ty check`, changed-file `uv run --no-sync ruff
  check` and `ruff format --check`, and `git diff --check`: passed.
- The preserved read-only construction verifier: 25 of 25 reference cases
  passed, with all 533 supporting Article Chunks resolved. Its disposable report
  is `.scratch/query-construction/ticket-06-verification.json`.

The preserved batch has at most two semantic hops. The original campaign-to-
candidate-to-Bill extension and a three-hop article-topic extension are verified
on controlled data. The 25 reference checks remain development cases, not a
held-out Gold Set, and do not measure the production models' construction
quality. No acceptance criterion is blocked.

### Review closure, 2026-09-17

The two-axis review from fixed point `b323ca35` found one Standards judgement
call and one Spec gap. The Standards finding was valid: deterministic stage
checks ran in the Pydantic AI output validator and then repeated after each
accepted response. The validator now retains each checked result for the
retriever to consume, so correction feedback and retry behavior stay unchanged
without duplicate compiler work.

The Spec finding was also valid. The accepted reported-alongside cases contain
no question-semantic relationship; they connect two entities through fixed
`MENTIONED_IN` provenance and optionally scope the shared Article Chunk through
a Source Article. The compiler now owns that zero-semantic-hop shape, retains
the requested entity as the route entry node, and emits no semantic graph claim
for provenance edges. Controlled Neo4j cases cover both verified forms.

Review tracing also found that equal Bill Designations with a session on only
one slot could evade the multi-Bill broadcast guard. Repeated designations now
require one explicit and different session on every repeated slot. The existing
explicit multi-value assignment remains unchanged.

Verification passed:

- Focused structural tests: 75 passed, including 37 disposable-Neo4j cases.
- One final deterministic suite: 1086 passed, 47 opt-in integration tests
  skipped, with the same two existing provider warnings.
- Changed-module offline type checking, changed-file Ruff checking and format
  checking, and `git diff --check`: passed.

The ticket remains `completed`; no valid review finding is unresolved.
