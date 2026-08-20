# Decide which subgraph is retrievable now and which is deferred

Labels: wayfinder:grilling, needs-triage
Parent: [Useful Graph Retrieval](../MAP.md)
Blocked by: [Update the extraction prompt to the settled ontology and populate the graph](01-populate-graph-with-settled-ontology.md), [Decide the target question set for California political retrieval](02-target-question-set.md)

## Question

Given what extraction actually populated and which questions matter, which slice
of the ontology is retrievable today, and which is deferred until the
legislative and campaign-finance layers land?

The ontology is the design target in full, but a large part of it — `Bill`,
`LegislativeEvent`, `Committee`, `Prop`, `Campaign`, `FUNDED`, `LOBBIED_FOR` —
depends on roadmap outcome 5. This ticket names the first buildable slice, the
questions it can honestly answer, and how the retrieval layer behaves when a
question reaches into an unpopulated region: whether it declines, answers
partially with a stated gap, or degrades to news evidence alone.

That behaviour is contract surface, so this decision feeds the contract as well
as the build order.

## Blocking

- Blocks: Decide the retrieval modes and the index inventory they require.

## Comments

### Previously discussed — 2026-08-19 grilling session

Decisions the maintainer made in session. Recorded here as input to this
ticket, not as its resolution.

- **v1 covers six question families**: E1–E3 (entity lookup) and R1–R3
  (relationship lookup). M1–M3 (multi-hop traversal) are deferred to a second
  release, but the answer display is to be designed knowing they are coming —
  the path shown for a multi-hop result is a display concern this ticket should
  not foreclose. M4 and M5 are tagged `layer: outcome-5` in
  [question-set.md](../question-set.md) and are unreachable until CAL-ACCESS and
  Open States ingestion exists.
- **The corpus is CalMatters only for v1.** Additional publications wait until
  retrieval works. Each new publication costs a selector set and a healing loop,
  and the families that benefit from cross-outlet corroboration (M2, M3) are
  already cut from v1.
- **Corpus size at the time of this session**: `document_store.db` held 73
  stories — 14 `COMPLETED`, 59 `FAILED_DLQ`. The failures were predominantly
  coreference, which the
  [Coreference Mention Spans](../../../projects/coreference-mention-spans/PRD.md)
  rework addresses. Whatever completes after that rework is the graph this
  ticket rules against.
