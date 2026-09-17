# 04 — Dense retrieval from an approved rewrite

Labels: ready-for-agent

## Parent

[Graph-Prioritized Retrieval](../PRD.md)

## What to build

Embed the approved Query Rewrite and search the existing Article Chunk vector
index. Return ranked candidates through the shared branch contract so dense
evidence remains eligible when graph structure is absent or incomplete.

## Acceptance criteria

- [ ] Dense retrieval embeds only the approved Query Rewrite and cannot receive
      the original wording.
- [ ] Retrieval searches the existing Article Chunk vector index with the
      configured candidate limit.
- [ ] Every candidate identifies its Article Chunk, branch-local rank and score,
      and dense retrieval route.
- [ ] A candidate needs no matching graph route or extracted relationship to
      remain eligible.
- [ ] A completed vector search with no candidates returns the shared
      successful-empty outcome.
- [ ] Embedding, index, query execution, and deadline failures remain
      distinguishable in structured logs.
- [ ] Integration tests use deterministic embeddings to verify candidate
      identities, ordering, branch-local scores, and the empty outcome.

## Blocked by

- [02 — Retrieval execution and evidence contracts](02-retrieval-execution-and-evidence-contracts.md).
