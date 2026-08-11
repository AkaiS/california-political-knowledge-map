Labels: completed

## Parent

[News Ontology and Graph Population](../PRD.md)

## What to build

The write path stops disagreeing with the settled ontology about what things are
called. `:Article` becomes `:NewsArticle`, and `(Chunk)-[:BELONGS_TO]->(Article)`
becomes `(NewsArticle)-[:HAS_CHUNK]->(Chunk)` — a rename *and* a direction
change. The entity-to-chunk edge is already `MENTIONED_IN` directed from the core
entity to the chunk, which matches `ontology.md`; it is left alone.

`NewsArticle` and `Chunk` nodes keep their existing natural keys — the article
URL, and the article URL plus chunk index. Node identity for everything else is
ticket 06's concern; this ticket changes vocabulary only.

This is a prefactor, taken first and on its own: it is mechanical, it touches
every existing graph assertion in the suite, and doing it separately keeps ticket
06's substantive identity changes readable. The existing tests asserting the
superseded `:Article` and `BELONGS_TO` vocabulary are updated in place. No new
Neo4j integration tests are added beyond these renames.

## Acceptance criteria

- [x] Article nodes are written as `:NewsArticle`.
- [x] The article-to-chunk edge is `(NewsArticle)-[:HAS_CHUNK]->(Chunk)`, in that
      direction; `BELONGS_TO` is gone from the write path.
- [x] `MENTIONED_IN` still runs from the core entity to the chunk.
- [x] `NewsArticle` and `Chunk` keep the article URL and article-URL-plus-index
      keys.
- [x] The graph adapter and pipeline tests asserting the old vocabulary are
      updated in place and the suite is green.

## Blocked by

- None — can start immediately.
