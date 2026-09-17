# 04 — Dense retrieval from an approved rewrite

Labels: completed

## Parent

[Graph-Prioritized Retrieval](../PRD.md)

## What to build

Embed the approved Query Rewrite and search the existing Article Chunk vector
index. Return ranked candidates through the shared branch contract so dense
evidence remains eligible when graph structure is absent or incomplete.

## Acceptance criteria

- [x] Dense retrieval embeds only the approved Query Rewrite and cannot receive
      the original wording.
- [x] Retrieval searches the existing Article Chunk vector index with the
      configured candidate limit.
- [x] Every candidate identifies its Article Chunk, branch-local rank and score,
      and dense retrieval route.
- [x] A candidate needs no matching graph route or extracted relationship to
      remain eligible.
- [x] A completed vector search with no candidates returns the shared
      successful-empty outcome.
- [x] Embedding, index, query execution, and deadline failures remain
      distinguishable in structured logs.
- [x] Integration tests use deterministic embeddings to verify candidate
      identities, ordering, branch-local scores, and the empty outcome.

## Blocked by

- [02 — Retrieval execution and evidence contracts](02-retrieval-execution-and-evidence-contracts.md).

## Comments

### Public test seams recorded before implementation, 2026-09-17

The user's blanket advance confirmation covers these concrete public seams:

- `Neo4jDenseRetriever(driver, embedder=None, *, candidate_limit, database="neo4j")`
  and its asynchronous `retrieve(request: RetrievalRequest, *, deadline: float)`
  return the shared successful or failed branch outcome. The limit is a positive
  integer; the deadline is absolute event-loop time.
- The same retrieval entry point runs against the existing Article Chunk vector
  index in disposable Neo4j with deterministic HTTP embedding responses. Tests
  assert candidate identities, ordering, native scores, routes, limits, and
  successful emptiness without depending on Cypher text.
- Structured `retrieval_branch_failed` records observed at that entry point
  distinguish embedding preparation, index availability, execution, and deadline
  failures. Faults enter through the external HTTP and Neo4j boundaries.

### Implementation and verification, 2026-09-17

Implemented `Neo4jDenseRetriever` and documented its public interface in
[dense retrieval](../../../../docs/dense-retrieval.md). The existing asynchronous
embedding client receives only the approved question through `embed_query`.
Read-only retrieval verifies the ingestion adapter's `chunk_vector_index` and
passes the configured limit to vector search. Candidates retain chunk and
Source Article identity, native score, branch rank, and the dense route without
requiring extracted entities or relationships.

An empty vector search succeeds. Embedding preparation, index availability,
query execution, and deadline failures emit distinct safe structured records.
The shared deadline covers embedding transport retries and all database work;
remaining time also becomes each query's transaction timeout. The retriever
adds no retry loop. Initial pipeline limits remain issue 07's responsibility.

TDD slices observed failures before implementing ranking, index compatibility,
database error classification, deadlines, embedding failures, server timeout
and index-loss classification, and candidate-limit validation. Live integration
also caught Neo4j's uppercase `COSINE` metadata, which the check now accepts.

Verification passed:

- `uv run --no-sync pytest -q tests/test_dense_retrieval.py`: 30 passed.
- `uv run --no-sync pytest -q tests/test_dense_retrieval.py tests/test_full_text_retrieval.py tests/test_retrieval_contracts.py`:
  92 passed.
- `RUN_NEO4J_INTEGRATION=1 uv run --no-sync pytest -q tests/integration/test_dense_neo4j.py tests/integration/test_full_text_neo4j.py`:
  10 passed against disposable Neo4j 2026.07.1. The dense tests verify ranked
  identities, native scores, routes, configured limits, absence of extracted
  relationships, empty success, and actual missing-index failure.
- `uv run --no-sync pytest -q`: 1048 passed, 10 opt-in integration tests skipped,
  and the two existing provider warnings.
- Changed-file `uvx --offline ty check`, `uv run --no-sync ruff check`, and
  `git diff --check`: passed.

Commands used `UV_CACHE_DIR=/private/tmp/ca-map-uv-cache`. The project environment
did not include `ty`; `uvx` supplied it without changing project dependencies.
No acceptance criterion is blocked. These tests establish behavior on a
controlled graph, not retrieval quality on the political corpus.
