# Decide the target question set for California political retrieval

Labels: wayfinder:grilling, ready-for-human
Parent: [Useful Graph Retrieval](../MAP.md)

## Question

What questions must this retrieval layer answer, expressed concretely enough to
choose retrieval modes against and to build an Evaluation Gold Set from later?

The roadmap names four orientations — entity, edge, neighborhood, and community.
This ticket turns them into an authored set of representative questions over the
settled ontology, each one traced to the subgraph and traversal that would answer
it, so that later tickets can be judged against real targets rather than
abstractions.

It should also distinguish questions the graph is meant to answer from questions
it must decline, since answers are meant to direct readers to original reporting
rather than substitute for it.

## Blocking

- Blocks: Decide which subgraph is retrievable now and which is deferred.
- Blocks: Prototype query construction and validation against the ontology.
- Blocks: Decide the retrieval modes and the index inventory they require.
