# 03. Apply and roll back reviewed provenance

Labels: ready-for-agent

## Parent

[One-Time Legacy Chunk Provenance Backfill](../PRD.md)

## What to build

Let the maintainer apply a reviewed plan for a selected Source Article to a
test graph, inspect exactly what changed, and reverse that run if needed. The
operation must be conditional and safe to repeat. Building this command does
not authorize a run against the user's live databases.

## Acceptance criteria

- [ ] Apply requires an explicit reviewed plan, target database identity,
      backup reference, and confirmation. It has no implicit live target.
- [ ] Before each write, apply rechecks Chunk ownership and text digest, Story
      digest, range bounds, and previous provenance. A mismatch skips the
      Chunk and appears in the result.
- [ ] Apply changes only the original range and Story-content fingerprint on
      an eligible Neo4j Chunk. It does not alter stored wording, embeddings,
      identities, relationships, or SQLite Stories.
- [ ] An applied manifest records every changed Chunk and its previous values.
      Repeating the same plan is idempotent and never overwrites newer normal
      ingestion or another backfill.
- [ ] Rollback uses that manifest and restores only properties still matching
      this run's write. A later change is reported and left intact.
- [ ] Command-level tests prove a successful apply, skipped stale input,
      repeat apply, guarded rollback, and no write without explicit approval.

## Blocked by

- [01. Inventory and map verbatim legacy Article Chunks](01-inventory-and-map-verbatim-legacy-chunks.md)

This ticket does not depend on 02. It can use a reviewed verbatim plan while
coreferenced alignment is developed separately.
