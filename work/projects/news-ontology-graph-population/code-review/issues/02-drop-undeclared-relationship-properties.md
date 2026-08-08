Labels: ready-for-agent

## Parent

[Code Review: News Ontology and Graph Population, issues 02–07](../README.md)

## What to build

The PRD's drop-and-log rule holds on both sides of an edge. Today an unknown
node property name is dropped and recorded, while an unknown *relationship*
property name passes straight through to the graph.

Relationship properties become write-path-owned. A model-supplied relationship
property that the relationship's shape does not declare is dropped and recorded
in the Adherence Report, symmetric with node properties. The only values that
reach an edge are ones the system put there deliberately.

## Acceptance criteria

- [ ] A relationship property not declared by the relationship's shape is
      dropped during conformance and recorded with its chunk.
- [ ] Declared relationship properties are untouched.
- [ ] A relationship whose properties are entirely undeclared still produces the
      relationship; only the properties are lost.
- [ ] The drop is recorded under its own Adherence Report category, distinct
      from node property drops.
- [ ] The suite is green.

## Blocked by

- [01 Gate conformance on the extracted-label subset](01-gate-conformance-on-extracted-labels.md)
