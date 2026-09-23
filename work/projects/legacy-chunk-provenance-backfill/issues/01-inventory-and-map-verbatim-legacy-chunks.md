# 01. Inventory and map verbatim legacy Article Chunks

Labels: ready-for-agent

## Parent

[One-Time Legacy Chunk Provenance Backfill](../PRD.md)

## What to build

Give the maintainer a read-only command that counts existing Article Chunks
without original Story provenance and proposes ranges for chunks whose stored
wording has one exact, order-consistent location in the cited Story. The report
must show what can be mapped now and why the rest cannot. Running it must not
change either database.

## Acceptance criteria

- [ ] The command defaults to read-only operation and reports total Stories,
      Article Chunks, chunks already carrying provenance, proposed mappings,
      and skips by reason.
- [ ] A proposal has a half-open original Story range, Story-content digest,
      stored Chunk-text digest, Chunk and Source Article identities, and the
      previous provenance values needed by a later guarded apply.
- [ ] A verbatim Chunk receives a proposal only when its Story location is
      unique and consistent with neighboring Chunk order. Repeated wording is
      not resolved by taking the first match.
- [ ] Missing Stories, conflicting ownership, ambiguous locations, and
      existing provenance are reported without changing data.
- [ ] The report includes reviewable examples of stored Chunk wording beside
      proposed original Story passages and keeps raw run artifacts out of Git.
- [ ] Command-level tests prove the reported ranges and that dry run leaves
      both stores unchanged.

## Blocked by

None. This is the current frontier.
