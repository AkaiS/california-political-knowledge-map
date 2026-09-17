# 05 — Typed structural retrieval to Grounding Evidence

Labels: ready-for-agent

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

- [ ] Structural retrieval receives only the approved Query Rewrite.
- [ ] No model produces free-form Cypher, identifiers, variables, parameter
      names, projections, or provenance paths.
- [ ] Code owns legal graph shapes, validation, Cypher compilation, execution,
      provenance traversal, Source Article lookup, and result hydration.
- [ ] Entity lookup and one-relationship questions produce ranked Article Chunk
      candidates through the shared branch contract.
- [ ] Bill-name values pass through the shared Bill Designation parser before
      entity resolution.
- [ ] Internal-ID lookup preserves duplicate identity ambiguity rather than
      silently selecting or merging a graph entity.
- [ ] Candidates retain their supporting graph claims and Grounding Evidence.
- [ ] Schema filtering, typed selection and wiring, binding, validation, Cypher
      execution, hydration, successful empty execution, and deadline exhaustion
      remain distinguishable.
- [ ] Controlled-graph tests cover entity lookup, one-relationship lookup, Bill
      Designation handling, identity ambiguity, successful empty execution, and
      each initial-attempt failure boundary.

## Blocked by

- [02 — Retrieval execution and evidence contracts](02-retrieval-execution-and-evidence-contracts.md).
