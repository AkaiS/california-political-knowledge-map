# 04. Rehearse and audit the corpus backfill

Labels: ready-for-agent

## Parent

[One-Time Legacy Chunk Provenance Backfill](../PRD.md)

## What to build

Show what the full backfill would do before any live migration. Rehearse the
command against a copied SQLite Story store and disposable Neo4j data, test an
interrupted run and rollback there, then give the maintainer a coverage and
skip report for deciding whether a live apply is worth doing.

## Acceptance criteria

- [ ] The rehearsal identifies its copied database targets before running and
      does not write to the user's live SQLite store or Neo4j graph.
- [ ] The report gives proposal and skip counts by Story and Article Chunk,
      separates verbatim and coreferenced proposals, and lists unresolved
      Chunks for possible later selective reingestion.
- [ ] Apply on copied data can resume after interruption without duplicate
      writes. The post-apply audit checks every written range and Story
      fingerprint and reports conflicts separately.
- [ ] A rollback rehearsal restores this run's properties without deleting
      Chunks or graph relationships.
- [ ] Representative proposed passages, including a split-replacement
      boundary, are reviewed against their original Stories. The report makes
      clear that alignment does not prove the old Coreference Resolution was
      semantically correct.
- [ ] The project records a concise go-or-stop recommendation from the
      rehearsal. No live apply, whole-corpus reingestion, or retrieval cutover
      occurs under this ticket.

## Blocked by

- [02. Map uniquely anchored coreferenced Article Chunks](02-map-uniquely-anchored-coreferenced-chunks.md)
- [03. Apply and roll back reviewed provenance](03-apply-and-roll-back-reviewed-provenance.md)
