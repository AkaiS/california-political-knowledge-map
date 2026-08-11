Labels: ready-for-agent

## Parent

[Code Review: News Ontology and Graph Population, issues 02–07](../README.md)

## What to build

The data crossing the Graph Database Adapter boundary is typed, per
[ADR 0002](../../../../docs/adr/0002-story-pipeline-architecture.md). Two things
currently breach it.

**Bill Session Resolution** crosses the boundary as a nested dictionary of
objects. It becomes a Pydantic domain model.

**The Adherence Report** is a dictionary indexed by literal category strings at
every drop site. It becomes a Pydantic model whose drop categories are a closed
enumeration, so a mistyped category name fails loudly instead of silently
creating a new bucket that nobody reads.

Behavior at the boundary is otherwise unchanged from what issue 07 built.

## Acceptance criteria

- [x] Bill Session Resolution is a Pydantic model at the adapter boundary.
- [x] The Adherence Report is a Pydantic model.
- [x] Drop categories are a closed enumeration; no drop site indexes by string
      literal.
- [x] An unrecognized category is a type error, not a new bucket.
- [x] Bill session resolution behavior through the Story Pipeline is unchanged.
- [x] The suite is green.

## Blocked by

- [02 Drop undeclared relationship properties](02-drop-undeclared-relationship-properties.md)
