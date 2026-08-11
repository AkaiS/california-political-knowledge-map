Labels: ready-for-agent

## Parent

[Code Review: News Ontology and Graph Population, issues 02–07](../README.md)

## What to build

An Article Chunk stops dying over one bad entity. Today conformance admits a
model-emitted `NewsArticle` or `Chunk` node because it checks the full News
Ontology label set, and then the write path rejects that same node because it
checks the extracted-label subset. The rejection raises, so the whole chunk
reaches the dead letter queue — the outcome the PRD forbids.

Conformance gates node labels on the **extracted-label subset**: the News
Ontology labels minus the write-path-owned `NewsArticle` and `Chunk`. A
model-emitted article node is dropped and recorded in the Adherence Report like
any other off-ontology output, and the twelve conforming entities beside it
survive. The Graph Database Adapter's label rejection stays exactly where it is,
demoted to an internal invariant that conformance now guarantees cannot fire.

In the same change, conformance moves out of the Entity Extraction Adapter into
the ontology package as a **pure function**: it takes an extraction result and a
chunk identifier and returns the conformed result together with the drops it
made. The adapter calls it and tallies the drops. This satisfies the PRD's
requirement that conformance happen at the untrusted-input boundary — the
boundary is what calls it — while making the whole ontology-to-conformance loop
testable without constructing an adapter or a model.

## Acceptance criteria

- [x] Conformance rejects a node label outside the extracted-label subset,
      including `NewsArticle` and `Chunk`.
- [x] A response mixing one such node with conforming entities yields the
      conforming entities and a recorded drop, and raises nothing.
- [x] Conformance is an importable pure function in the ontology package,
      returning the conformed result and its drops.
- [x] The Entity Extraction Adapter calls that function and is the only place
      that touches the Adherence Report.
- [x] The Graph Database Adapter's label check is unchanged in behavior.
- [x] The suite is green.

## Blocked by

- None — can start immediately.
