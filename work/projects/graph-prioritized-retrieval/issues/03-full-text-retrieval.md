# 03 — Full-text retrieval from an approved rewrite

Labels: completed

## Parent

[Graph-Prioritized Retrieval](../PRD.md)

## What to build

Turn an approved Query Rewrite into deterministic keywords and retrieve ranked
Article Chunk candidates through the accepted full-text indexes. Entity-name
and Source Article-title matches lead to Grounding Evidence without being
treated as support for a political claim by themselves.

## Acceptance criteria

- [x] Keyword extraction is deterministic and introduces no model agent or
      model retry loop.
- [x] Full-text retrieval searches entity names, Source Article titles, and
      Article Chunk text through the accepted index inventory.
- [x] Every branch candidate identifies its Article Chunk, branch-local rank
      and score, retrieval route, and matched field.
- [x] Name and title matches resolve to candidate Grounding Evidence without
      being represented as supporting graph claims.
- [x] A completed search with no candidates returns the shared successful-empty
      outcome.
- [x] Preparation, index, query execution, and deadline failures remain
      distinguishable in structured logs.
- [x] Disposable-Neo4j integration tests verify entity-name, Source
      Article-title, and Article Chunk-text retrieval.
- [x] Tests do not require a ranking algorithm that Neo4j does not guarantee.
      The public behavior remains full-text retrieval with branch-local scores.

## Blocked by

- [02 — Retrieval execution and evidence contracts](02-retrieval-execution-and-evidence-contracts.md).

## Comments

2026-09-17: Before editing implementation or tests, inspection identified these
public seams under the maintainer's advance confirmation:

- `extract_full_text_keywords(QueryRewrite)` returns deterministic search terms
  from the approved question.
- `await Neo4jFullTextRetriever.ensure_indexes()` installs the accepted three
  full-text indexes and ten non-unique internal-ID indexes in disposable Neo4j.
- `await Neo4jFullTextRetriever.retrieve(RetrievalRequest, deadline=...)` returns
  the shared successful, successful-empty, or failed branch outcome. Disposable
  Neo4j verifies real name, title, and text matches, candidate provenance,
  retained routes, and branch-local scores. Offline tests inject faults only at
  the Neo4j driver boundary and observe outcomes and structured failure logs.

The deadline is absolute event-loop time, so the later coordinator can pass one
deadline to concurrently running branches. The caller owns the async driver.

2026-09-17: Implemented the full-text adapter and documented its use in
[full-text retrieval](../../../../docs/full-text-retrieval.md). Index setup
installs the accepted three full-text indexes and ten non-unique ID indexes.
Read-only retrieval verifies online index schemas, searches deterministic quoted
terms, and resolves all eight entity labels, titles, and chunk text to grounded
Article Chunks. Policy Area names follow article-level topic edges. Every
match-to-chunk contribution retains its route, entry node and element ID,
Source Article, rank, and native score. Duplicate entity IDs stay distinct and
discovery matches carry no supporting graph claims.

Each index retains its native score ordering; round-robin interleaving avoids
comparing scores between indexes. Multiple contributions to one chunk remain
available for fusion to retain. Configurable candidate limits belong to issue
07. Successful searches without grounded candidates return the shared empty
success. Safe logs distinguish preparation, index, execution, and deadline
failures. Both asyncio cancellation and server transaction timeouts consume the
same caller-supplied deadline, with a final expiry check before success.

The TDD slices observed failures before adding keyword preparation, index setup,
name/title/text retrieval, Policy Area grounding, each failure category, stored
candidate validation, and final deadline enforcement. Verification passed:

- `uv run --no-sync pytest -q tests/test_full_text_retrieval.py`: 16 passed.
- `RUN_NEO4J_INTEGRATION=1 uv run --no-sync pytest -q tests/integration/test_full_text_neo4j.py`:
  8 passed against disposable Neo4j 2026.07.1, including all match fields, all
  entity labels, duplicate identities, retained routes and scores, emptiness,
  and an actual missing index. Containers were stopped and removed afterwards.
- `uv run --no-sync pytest -q`: 1018 passed, 8 opt-in integration tests skipped,
  and the two existing provider warnings.
- Changed-file `ty check`, `ruff check`, and `git diff --check`: passed.

Commands used `uv` with a writable temporary cache; the type checker used the
existing temporary tool environment. No acceptance criterion is blocked. The
coordinator, fusion, and original-wording verification remain with their own
tickets. Tests assert returned identities, routes, and native score ordering,
without assuming a specific Neo4j scoring algorithm.
