Labels: completed

## Parent

[News Ontology and Graph Population](../PRD.md)

## What to build

Extracted entities gain an identity of their own, structural provenance to their
source, and automatic topic edges — so that re-ingestion is idempotent, any
retrieved fact is traceable to the Article Chunk it came from, and later
authoritative ingestion can find news-derived structure by query.

Today everything is merged on `name` alone. Every node other than `NewsArticle`
and `Chunk` is instead merged on a **deterministic derived primary key** of the
form `label:slug(name)`, with `name` retained as a property. Readability is
deliberate: the graph will be inspected by hand to produce the parent ticket's
label inventory. Known limitation, recorded rather than solved — name-derived keys
leave "Newsom" and "Gavin Newsom" as separate nodes. That is Entity Resolution,
which the map places out of scope.

Sub-labels arriving from the conformed extraction result are written as
additional real Neo4j labels after whitelist validation, so a query can match a
labor union directly instead of scanning every organization's properties.

The write path owns `NewsArticle` and `Chunk` entirely — metadata the pipeline
already holds exactly is never guessed by a model — and creates the provenance
edges itself rather than depending on the model remembering to emit them:
`MENTIONED_IN` for every extracted entity, and `DISCUSSES_TOPIC` from the Article
Chunk to every `PolicyArea` node in that chunk's extraction. The topic edge
carries no properties and no nuance — the topic's presence in the chunk is the
entire edge — so a dedicated output field would buy nothing over the node already
being there. Article-level `DISCUSSES_TOPIC` is not materialized.

Every node and relationship the extractor produces is stamped with a provenance
property identifying it as news-derived, and shortcut relationships additionally
carry `skips` naming the primary-ontology node they bypass. Relying instead on
reachability from a chunk would fail the moment entity resolution merges a
news-derived node with one from an authoritative source. Each shortcut is, in
effect, the reconciliation specification written in advance: it names the
intermediate node later ingestion must insert and the edge it must re-anchor.

## Acceptance criteria

- [x] Non-article nodes merge on `label:slug(name)` with `name` kept as a
      property, and re-ingesting the same extraction twice creates no duplicates.
- [x] Sub-labels are written as additional Neo4j labels, after whitelist
      validation.
- [x] `MENTIONED_IN` is created automatically for every extracted entity.
- [x] `DISCUSSES_TOPIC` is created automatically from the chunk to each
      `PolicyArea` in that chunk's extraction, with no properties; no
      article-level topic edge is written.
- [x] Every extractor-produced node and relationship is traceable to the Article
      Chunk it came from *without* a provenance property: every extracted entity
      carries `MENTIONED_IN` to its Article Chunk, and every extractor-produced
      relationship carries the list of chunks that asserted it. That chunk list
      is load-bearing and must not be removed. This supersedes the original
      criterion — "every extractor-produced node and relationship carries the
      news-derived provenance property" — and the body paragraph above it; see the
      amended provenance paragraph under "Write path and the Graph Database
      Adapter" in the [PRD's Implementation Decisions](../PRD.md).
- [x] Shortcut relationships carry `skips` naming the bypassed node.
- [x] Covered at the graph adapter seam by inspecting the Cypher and parameters
      issued to a captured driver.

## Blocked by

- [02 — Ontology package, News Ontology, and the conformance check](02-ontology-package-and-conformance-check.md)
- [04 — Sub-labels and Entity Extraction Adapter conformance](04-sub-labels-and-extraction-conformance.md)
- [05 — Write-path ontology vocabulary rename](05-write-path-ontology-vocabulary-rename.md)
