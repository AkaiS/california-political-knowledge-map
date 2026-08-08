Labels: ready-for-agent

## Parent

[Code Review: News Ontology and Graph Population, issues 02–07](../README.md)

## What to build

One relationship-writing routine, shared by both ingestion entry points. Today
the same relationship write is spelled out twice, so a change to edge semantics
can land in one path and miss the other.

This is a prefactor with no behavior change. It is taken first and on its own so
that ticket 06 — which changes what a relationship *means* — lands in exactly one
place and is readable as a semantic change rather than a diff repeated twice.

## Acceptance criteria

- [ ] Both ingestion entry points call the same relationship-writing routine.
- [ ] The duplicated write is gone.
- [ ] The graph produced is byte-identical to before: no test assertion changes.
- [ ] The suite is green.

## Blocked by

- None — can start immediately.
