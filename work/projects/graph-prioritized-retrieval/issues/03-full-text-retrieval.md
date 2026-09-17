# 03 — Full-text retrieval from an approved rewrite

Labels: ready-for-agent

## Parent

[Graph-Prioritized Retrieval](../PRD.md)

## What to build

Turn an approved Query Rewrite into deterministic keywords and retrieve ranked
Article Chunk candidates through the accepted full-text indexes. Entity-name
and Source Article-title matches lead to Grounding Evidence without being
treated as support for a political claim by themselves.

## Acceptance criteria

- [ ] Keyword extraction is deterministic and introduces no model agent or
      model retry loop.
- [ ] Full-text retrieval searches entity names, Source Article titles, and
      Article Chunk text through the accepted index inventory.
- [ ] Every branch candidate identifies its Article Chunk, branch-local rank
      and score, retrieval route, and matched field.
- [ ] Name and title matches resolve to candidate Grounding Evidence without
      being represented as supporting graph claims.
- [ ] A completed search with no candidates returns the shared successful-empty
      outcome.
- [ ] Preparation, index, query execution, and deadline failures remain
      distinguishable in structured logs.
- [ ] Disposable-Neo4j integration tests verify entity-name, Source
      Article-title, and Article Chunk-text retrieval.
- [ ] Tests do not require a ranking algorithm that Neo4j does not guarantee.
      The public behavior remains full-text retrieval with branch-local scores.

## Blocked by

- [02 — Retrieval execution and evidence contracts](02-retrieval-execution-and-evidence-contracts.md).
