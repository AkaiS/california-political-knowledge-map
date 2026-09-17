# 05 — Typed structural retrieval to Grounding Evidence

Labels: completed

## Parent

[Graph-Prioritized Retrieval](../PRD.md)

## What to build

Productionize a narrow path through the atomic semantic constructor selected by
the query-construction prototype. For an approved Query Rewrite, models filter
the semantic schema, select and wire compiler-owned pieces, and bind values.
Code validates the result, compiles read-only Cypher, executes it, follows
provenance, and hydrates Grounding Evidence.

This ticket makes entity lookup and one-relationship questions work end to end.
The next ticket extends the same path to bounded multi-hop questions and
correction attempts.

## Acceptance criteria

- [x] Structural retrieval receives only the approved Query Rewrite.
- [x] No model produces free-form Cypher, identifiers, variables, parameter
      names, projections, or provenance paths.
- [x] Code owns legal graph shapes, validation, Cypher compilation, execution,
      provenance traversal, Source Article lookup, and result hydration.
- [x] Entity lookup and one-relationship questions produce ranked Article Chunk
      candidates through the shared branch contract.
- [x] Bill-name values pass through the shared Bill Designation parser before
      entity resolution.
- [x] Internal-ID lookup preserves duplicate identity ambiguity rather than
      silently selecting or merging a graph entity.
- [x] Candidates retain their supporting graph claims and Grounding Evidence.
- [x] Schema filtering, typed selection and wiring, binding, validation, Cypher
      execution, hydration, successful empty execution, and deadline exhaustion
      remain distinguishable.
- [x] Controlled-graph tests cover entity lookup, one-relationship lookup, Bill
      Designation handling, identity ambiguity, successful empty execution, and
      each initial-attempt failure boundary.

## Blocked by

- [02 — Retrieval execution and evidence contracts](02-retrieval-execution-and-evidence-contracts.md).

## Comments

### Public test seams and implementation, 2026-09-17

The user's blanket advance confirmation covers the concrete seams recorded in
[structural retrieval](../../../../docs/structural-retrieval.md) before tests or
implementation were added: `Neo4jStructuralRetriever.retrieve` and
`get_structural_agents`. Tests observe branch results and structured logs through
those interfaces, using scripted model responses and external Neo4j boundaries.

The atomic constructor from `511eaeee` now has a production path for one entity
or one relationship. Models filter the News Ontology, select compiler-owned
pieces, wire positional occurrences, and bind values. Code validates labels and
endpoints, parses Bill Designations, compiles parameterized read-only Cypher,
traverses provenance, and hydrates candidate Grounding Evidence. The shared
candidate contract retains that optional hydrated evidence without changing
the full-text or dense producers. Hydrated wording still requires original
Story verification by ticket 08's Evidence Assembler.

Duplicate internal IDs remain separate candidates with their physical element
IDs. Claim Keys, endpoint identities, review flags, and provenance survive
hydration. Article-level topic claims follow their Source Articles. Successful
empty traversal differs from failed construction and from a matched claim with
broken grounding. Detailed safe failure stages and model usage remain in logs.

TDD slices observed failures before implementing entity hydration, relationship
claims, Bill normalization, identity ambiguity, failure classification,
deadlines, topic provenance, date bounds, broken-grounding detection, usage
accounting, and exact wording retention.

Verification passed:

- Focused structural and shared-contract tests: 66 passed.
- Disposable Neo4j integration across structural, dense, and full-text branches:
  26 passed, including 16 structural cases.
- One final deterministic suite: 1068 passed, 26 opt-in integration tests skipped,
  and the two existing provider warnings.
- Changed-file `uvx --offline ty check`, `uv run --no-sync ruff check`, and
  `git diff --check`: passed.

Project commands used `UV_CACHE_DIR=/private/tmp/ticket-05-uv-cache`.
`uvx --offline` used the installed type checker without changing dependencies.
No acceptance criterion is blocked. Multi-hop construction and correction
attempts remain ticket 06 work. Live model quality remains unmeasured; the
controlled graph is behavioral evidence, not a Gold Set.

### Review closure, 2026-09-17

A two-axis review from fixed point `d2413cc3` found no Spec gaps or scope creep.
The Standards review found that the new API used generic schema terminology for
the News Ontology and repeated its parent/sub-label mapping. The review fix
renamed the new ontology-filter types and seam, derives supported sub-label
parents from `news.SUB_LABELS`, and restricts the ticket-05 selection contract
to its implemented maximum of two roles and one relationship. The existing
`schema_filtering` failure-stage value remains because ticket 02 already made it
part of the shared retrieval contract and this ticket explicitly requires that
stage to stay distinguishable.

The suggested `Piece`/selected-piece value-object refactor was not taken. Those
values are private, immutable, compiler-created catalog data; external model
selections are checked against the catalog before use. Adding a public wrapper
would not close an exposed invalid state in this ticket and would pre-shape the
multi-hop representation owned by ticket 06.

Review verification passed:

- Focused structural and shared-contract tests: 68 passed.
- Disposable Neo4j structural integration tests: 16 passed.
- Final deterministic suite: 1070 passed, 26 opt-in integration tests skipped,
  and the same two existing provider warnings.
- Changed-file `uvx --offline ty check`, `uv run --no-sync ruff check`, and
  `git diff --check`: passed.

The ticket remains `completed`; no valid review finding is unresolved.
