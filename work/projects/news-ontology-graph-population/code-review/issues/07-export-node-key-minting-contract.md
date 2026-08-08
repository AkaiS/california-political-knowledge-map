Labels: ready-for-agent

## Parent

[Code Review: News Ontology and Graph Population, issues 02–07](../README.md)

## What to build

Node primary key minting becomes an importable ontology-level contract: one
module exporting the general derived key and the Bill key. Today those
expressions are inlined at their call sites, and the Bill key expression is
re-derived in two places.

This is not speculative generality. A key that two ingesters must agree on
byte-for-byte is the difference between a later legislative ingester *enriching*
a news-derived Bill and creating a second Bill node beside it. Making the
minting rule a lookup is what lets that ingester get it right without reading
the news write path.

Both existing Bill key call sites import the shared function.

## Acceptance criteria

- [x] An importable module in the ontology package exports the general derived
      key and the Bill key.
- [x] Both existing Bill key call sites import it; the expression appears once.
- [x] Keys written to the graph are unchanged from before.
- [x] The suite is green.

## Blocked by

- None — can start immediately.
