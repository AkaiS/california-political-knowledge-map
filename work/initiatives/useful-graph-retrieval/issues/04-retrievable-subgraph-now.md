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
