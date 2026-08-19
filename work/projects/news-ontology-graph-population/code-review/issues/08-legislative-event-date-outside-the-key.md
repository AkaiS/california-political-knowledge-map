Labels: completed

## Parent

[Code Review: News Ontology and Graph Population, issues 02–07](../README.md)

## What to build

A `LegislativeEvent` records a date, so that a later reconciliation against an
authoritative legislative source has the fact it needs. The date is the event's
stated date where the article supplies one, otherwise the article's published
date, with the source flagged the same way Bill Session Resolution flags
verified against inferred.

**The date is never part of the key.** The `Bill` precedent does not transfer.
Bill numbers collide across sessions by design, so a weak Bill key *conflates*
two distinct bills, which is unrecoverable. A Legislative Event's failure mode is
the opposite: a weak key *fragments* one event into two nodes, which a later join
on date and bill can repair. Putting a guessed date in the key would trade the
recoverable failure for the unrecoverable one. A date-in-key-only-when-verified
rule is also refused, because it creates the second identity shape the PRD
explicitly rules out — a later correct-date ingest must be able to find every
node it has to fix, and it can only do that if there is one shape to look for.

The key stays name-derived, from the shared minting contract.

## Acceptance criteria

- [x] A `LegislativeEvent` carries a `date` and a flag naming its source.
- [x] The date is the event's stated date when the article supplies one.
- [x] The date falls back to the article's published date otherwise, flagged as
      inferred.
- [x] The event's primary key does not contain the date, verified or inferred.
- [x] Every `LegislativeEvent` has the same identity shape.
- [x] The suite is green.

## Blocked by

- [07 Export node primary key minting as an ontology contract](07-export-node-key-minting-contract.md)
