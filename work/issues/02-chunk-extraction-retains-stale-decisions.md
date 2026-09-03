# Reprocessing an article leaves its old chunk extractions in the graph

Labels: ready-for-agent

## Context

The article-level topic write was fixed on 2026-09-03 to replace this article's
topic decisions rather than add to them: `ingest_article_topics` retracts the
`DISCUSSES_TOPIC` and `ABOUT_TOPIC` edges the latest run no longer supports
before merging what it does. The chunk-level write path has the same defect and
was left alone, because scoping a retraction there is a different problem.

## The problem

`Neo4jAdapter.ingest_chunk` and `Neo4jAdapter.ingest_chunk_extraction` are
merge-only. Nothing removes what an earlier run of the same Source Article
wrote, so reprocessing accumulates:

- **Stranded Article Chunks.** A chunk's id is `<url>#chunk_<index>`. An
  article that re-chunks into fewer chunks than before leaves every tail chunk
  in place, with its old text, its old embedding, and its `HAS_CHUNK` edge. The
  vector index still returns it, so retrieval can ground an answer in text the
  article no longer contains.
- **Stale relationship claims.** A relationship the current extraction does not
  produce keeps its edge and keeps the chunk in `r.chunks`, so a claim reads as
  asserted by a chunk that no longer asserts it — and, where the chunk was
  stranded, by a chunk that no longer exists in the article.
- **Stale `MENTIONED_IN` edges**, and the nodes they hang off, for entities the
  current extraction does not name.

Re-chunking is not hypothetical: the chunker's output moves whenever the
resolved text moves, which Coreference Resolution can do on any re-run.

## What makes this harder than the topic fix

`DISCUSSES_TOPIC` hangs off the Source Article, so an article's own edges are
reachable from the article's node. `ABOUT_TOPIC` hangs between a measure and a
Policy Area, and was scoped by the provenance the edge now carries: `r.articles`,
appended the way `r.chunks` already was.

A chunk-level claim is shared the same way an `ABOUT_TOPIC` claim is: two
articles asserting the same relationship at equal Claim Key values produce one
edge, and `r.chunks` is what records who is asserting it. So the retraction is
the `r.chunks` analogue of the one written for `r.articles` — withdraw this run's
chunks, delete the edge when the list empties — plus a decision about the
stranded chunks and the nodes left with no `MENTIONED_IN` edge, neither of which
the topic fix had to make.

Both a node with no surviving mention and a chunk with no surviving article are
orphans, and the ontology does not currently say whether an orphan is deleted or
kept. That decision belongs in this issue, not in the write path.

## What to build

- Reprocessing a Source Article leaves the graph holding exactly the Article
  Chunks the latest run produced, and no others.
- A relationship edge's `chunks` list holds exactly the chunks of the latest run
  that assert it, plus whatever other articles' chunks already asserted it. An
  edge no chunk asserts any longer does not survive.
- The stranded-node question is decided and recorded: an entity node whose last
  `MENTIONED_IN` edge is retracted is either deleted or deliberately kept, with
  the reason written down where the decision can be found.
- Deterministic coverage drives the adapter twice over the same article — once
  with a longer extraction, once with a shorter one — and reads the Cypher, as
  `tests/test_article_topics.py` does.

## Acceptance criteria

- [ ] A second ingestion of an article that produces fewer chunks leaves no
      chunk from the first run in the graph.
- [ ] A relationship the second run does not produce loses that run's chunks
      from `r.chunks`, and the edge is deleted when no chunk asserts it.
- [ ] A relationship two articles assert survives one of them retracting it.
- [ ] The orphan decision is recorded and the write path matches it.
- [ ] Tests cover the shorter-re-run case and the two-article shared-claim case.

## Blocked by

None.
