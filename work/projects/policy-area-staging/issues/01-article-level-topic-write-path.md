# 01 — The article-level topic write path

Labels: completed

## Parent

[Policy Area Staging](../PRD.md)

## What to build

The database adapter gains one way to write what a Source Article is about: the
article, the Policy Areas it discusses, and the assignments from measures named
in it to those areas. It writes the `DISCUSSES_TOPIC` edge from the Source
Article that the News Ontology declares and nothing has ever produced, and the
`ABOUT_TOPIC` edges from Bills and Props to areas.

This is the seam both new stages will write through, built first and alone so
that neither stage has to invent one. Nothing calls it yet; a caller arrives in
02 with areas and in 04 with assignments. Passing no assignments is a normal
call, not an empty edge case, because that is exactly what the pipeline does
between 02 and 04.

A Policy Area node is keyed the way every non-Bill node is keyed, from its label
and its name, so the hub one article's classification writes is the same node a
later article reaches. The method extends the adapter Protocol the pipeline
already declares rather than adding a second seam, and it is named for the level
it works at, so an article-level edge stays visibly article-level next to the
per-chunk write beside it.

## Acceptance criteria

- [x] The database adapter Protocol declares one method taking a Source Article,
      its Policy Areas, and its topic assignments.
- [x] The Neo4j adapter merges a `PolicyArea` node per area, keyed from label and
      name by the same derivation every non-Bill node uses, and merges
      `(:NewsArticle)-[:DISCUSSES_TOPIC]->(:PolicyArea)`.
- [x] Each assignment merges `ABOUT_TOPIC` from the named `Bill` or `Prop` to the
      named `PolicyArea`, resolving the measure's node the same way the chunk
      extraction write resolves an endpoint, including a Bill whose Bill Session
      Resolution supplied its key.
- [x] A call with areas and no assignments writes the article edges and nothing
      else.
- [x] A call with neither writes nothing and does not fail.
- [x] Writing the same article's topics twice leaves one node per area and one
      edge per pair.
- [ ] The SQLite adapter satisfies the Protocol.
- [x] Nothing in the pipeline calls the new method yet, and the existing suite
      passes unchanged.

## Blocked by

- None — can start immediately.
