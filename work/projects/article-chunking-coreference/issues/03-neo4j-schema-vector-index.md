Labels: completed

## What to build

Update the Neo4j database model and ingestion transactions to store explicit metadata nodes representing Articles and Chunks, and create a vector search index.

Specifically, the ingestion pipeline must:
1. Create `(:Article)` nodes uniquely identified by `url`, setting properties for `title`, `author`, and `published_date`.
2. Create `(:Chunk)` nodes uniquely identified by `id` (e.g. `url + "#chunk_" + index`), setting `text`, `chunk_index`, and `embedding` (array of floats).
3. Connect each chunk to its article: `(Chunk)-[:BELONGS_TO]->(Article)`.
4. Connect all entities extracted from a chunk to that chunk: `(Entity)-[:MENTIONED_IN]->(Chunk)`.
5. Add a `source_chunk_id` property on the relationship edges between extracted entities to track which chunk supported the relationship.
6. Automatically create a Neo4j Vector Index (named `chunk_vector_index`) on the `embedding` property of `(:Chunk)` if it does not already exist.

## Acceptance criteria

- [x] Neo4j ingestion inserts `(:Article)` and `(:Chunk)` nodes and links them with `[:BELONGS_TO]`.
- [x] Extracted entities are linked to their source chunk using `[:MENTIONED_IN]`.
- [x] Relationship edges between extracted entities contain the correct `source_chunk_id` property.
- [x] The Neo4j Vector Index is successfully created and verified on connection.
- [x] Mocked Neo4j transactions in unit tests assert that all necessary Cypher statements are generated correctly.

## Blocked by

- [work/projects/article-chunking-coreference/issues/01-recursive-chunking.md](file:///Users/akaisenghor/Projects/california-political-knowledge-map/work/projects/article-chunking-coreference/issues/01-recursive-chunking.md) (completed)

## Comments

2026-08-05: Verified already implemented on `main` in
`src/knowledge_map/adapters/neo4j_db.py` (`_ensure_vector_index`,
`ingest_article`, `ingest_chunk`, `ingest_chunk_extraction`), covered by
`tests/test_graph_db.py` (23 passing). Relabeled `completed`.

### Previously discussed — 2026-08-19 grilling session

This issue is `completed`; the decision below changes what a `:Chunk` stores and
needs its own issue. Recorded here because this issue owns the schema.

[neo4j_db.py:271](../../../../src/knowledge_map/adapters/neo4j_db.py:271) writes
`c.text = $text, c.index = $index, c.embedding = $embedding`. `context`,
`start_index`, and `end_index` are computed in
[chunking.py](../../../../src/knowledge_map/utils/chunking.py), carried on
`ArticleChunk`, and then dropped at write time.

Decision: **persist `text`, `context`, `start_index`, and `end_index` on the
`:Chunk` node.** Retrieval returns whole Chunks with bracketed coreference
substitutions, and both the bracket positions and the sentence alignment need the
offsets. Nothing downstream should re-derive them.

Note, unchanged and confirmed: edge-level provenance already exists. A
relationship accumulates `r.chunks` at
[neo4j_db.py:131](../../../../src/knowledge_map/adapters/neo4j_db.py:131), and
entities link through `(n)-[:MENTIONED_IN]->(c)`. The graph already stores
`(head, relation, tail, chunk_id)`.
