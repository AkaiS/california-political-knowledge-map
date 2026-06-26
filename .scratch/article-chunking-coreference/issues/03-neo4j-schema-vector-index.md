Status: ready-for-agent

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

- [ ] Neo4j ingestion inserts `(:Article)` and `(:Chunk)` nodes and links them with `[:BELONGS_TO]`.
- [ ] Extracted entities are linked to their source chunk using `[:MENTIONED_IN]`.
- [ ] Relationship edges between extracted entities contain the correct `source_chunk_id` property.
- [ ] The Neo4j Vector Index is successfully created and verified on connection.
- [ ] Mocked Neo4j transactions in unit tests assert that all necessary Cypher statements are generated correctly.

## Blocked by

- [.scratch/article-chunking-coreference/issues/01-recursive-chunking.md](file:///Users/akaisenghor/Projects/california-political-knowledge-map/.scratch/article-chunking-coreference/issues/01-recursive-chunking.md)
