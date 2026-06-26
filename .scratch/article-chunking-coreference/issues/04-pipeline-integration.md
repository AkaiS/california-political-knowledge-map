Status: ready-for-agent

## What to build

Integrate the coreference resolution, text chunking, and Neo4j schema ingestion into the main playground CLI pipeline (`playground.py`'s `run` action).

The integrated flow for processing a story must:
1. Resolve coreferences on the story's `content` to produce clean plain text.
2. Split the clean plain text into `Article Chunks`.
3. Generate vector embeddings for each chunk.
4. Save the `(:Article)` node (merging on `url` and setting `title`, `author`, `published_date`).
5. Save each `(:Chunk)` node (merging on `url + "#chunk_" + index` and setting `text`, `chunk_index`, `embedding`), linking them via `(Chunk)-[:BELONGS_TO]->(Article)`.
6. For each chunk, run `extract_entities(chunk_text)`.
7. Ingest the extracted entities and relationships, linking the entities to the chunk via `[:MENTIONED_IN]`, and setting the `source_chunk_id` property on relationship edges.

## Acceptance criteria

- [ ] Processing an article via CLI `run` executes the full chunked extraction pipeline successfully.
- [ ] Embedding generation and entity extraction run chunk-by-chunk rather than on the full text.
- [ ] Ingestion creates all graph nodes, structural relationships, and edge properties as expected.
- [ ] Mocked integration tests verify the end-to-end flow from SQLite article load to Neo4j ingestion.

## Blocked by

- [.scratch/article-chunking-coreference/issues/01-recursive-chunking.md](file:///Users/akaisenghor/Projects/california-political-knowledge-map/.scratch/article-chunking-coreference/issues/01-recursive-chunking.md)
- [.scratch/article-chunking-coreference/issues/02-coreference-pipeline.md](file:///Users/akaisenghor/Projects/california-political-knowledge-map/.scratch/article-chunking-coreference/issues/02-coreference-pipeline.md)
- [.scratch/article-chunking-coreference/issues/03-neo4j-schema-vector-index.md](file:///Users/akaisenghor/Projects/california-political-knowledge-map/.scratch/article-chunking-coreference/issues/03-neo4j-schema-vector-index.md)
