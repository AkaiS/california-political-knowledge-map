# 02. Map uniquely anchored coreferenced Article Chunks

Labels: ready-for-agent

## Parent

[One-Time Legacy Chunk Provenance Backfill](../PRD.md)

## What to build

Extend the read-only plan to propose original Story ranges for old Article
Chunks whose stored wording changed during Coreference Resolution. Use exact
unchanged anchors and Chunk order. If the source range cannot be established
uniquely, leave that Chunk unmapped and say why.

## Acceptance criteria

- [ ] The command proposes a range for a uniquely aligned coreferenced Chunk
      without calling a model or changing the Story Pipeline or retrieval.
- [ ] Multiple length-changing replacements and the stored overlap prefix
      still produce a passage from the correct place in the original Story.
- [ ] A Chunk boundary inside a replacement includes the whole original
      mention only when the surrounding alignment establishes both edges.
      Otherwise the Chunk is skipped. No neighboring sentence is added.
- [ ] Repeated text, insufficient anchors, contradictory Chunk order, or
      competing source ranges are reported as skips, not accepted by fuzzy
      score or first-match lookup.
- [ ] The dry-run report separates verbatim proposals, coreferenced
      proposals, and unresolved Chunks so the maintainer can judge coverage.
- [ ] Command-level tests cover accepted and rejected mappings and prove that
      the command remains read-only.

## Blocked by

- [01. Inventory and map verbatim legacy Article Chunks](01-inventory-and-map-verbatim-legacy-chunks.md)
