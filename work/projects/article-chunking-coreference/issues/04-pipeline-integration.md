Labels: completed

## What to build

Integrate the coreference resolution, text chunking, and Neo4j schema ingestion into the main playground CLI pipeline (`playground.py`'s `run` action).

The integrated flow for processing a story must:
1. Resolve coreferences on the story's `content` to produce clean plain text.
2. Split the clean plain text into `Article Chunks` using the Chonkie-based chunking utility.
3. Generate vector embeddings for each chunk.
4. Save the `(:Article)` node (merging on `url` and setting `title`, `author`, `published_date`).
5. Save each `(:Chunk)` node (merging on `url + "#chunk_" + index` and setting `text`, `chunk_index`, `embedding`), linking them via `(Chunk)-[:BELONGS_TO]->(Article)`.
6. For each chunk, run `extract_entities(chunk_text)`.
7. Ingest the extracted entities and relationships, linking the entities to the chunk via `[:MENTIONED_IN]`, and setting the `source_chunk_id` property on relationship edges.

## Acceptance criteria

- [x] Processing an article via CLI `run` executes the full chunked extraction pipeline successfully.
- [x] Embedding generation and entity extraction run chunk-by-chunk rather than on the full text.
- [x] Ingestion creates all graph nodes, structural relationships, and edge properties as expected.
- [x] Mocked integration tests verify the end-to-end flow from SQLite article load to Neo4j ingestion.

## Blocked by

- [work/projects/article-chunking-coreference/issues/01-recursive-chunking.md](file:///Users/akaisenghor/Projects/california-political-knowledge-map/work/projects/article-chunking-coreference/issues/01-recursive-chunking.md) (completed)
- [work/projects/article-chunking-coreference/issues/02-coreference-pipeline.md](file:///Users/akaisenghor/Projects/california-political-knowledge-map/work/projects/article-chunking-coreference/issues/02-coreference-pipeline.md) (completed)
- [work/projects/article-chunking-coreference/issues/03-neo4j-schema-vector-index.md](file:///Users/akaisenghor/Projects/california-political-knowledge-map/work/projects/article-chunking-coreference/issues/03-neo4j-schema-vector-index.md) (completed)

## Comments

2026-08-05: Verified already implemented on `main`. Orchestration lives in
`src/knowledge_map/core/pipeline.py` (`StoryPipeline.run`: coreference →
`chunk_article` → per-chunk embeddings → per-chunk `extract` → Neo4j ingest);
wired into the CLI at `src/knowledge_map/cli/main.py` under the `ingest` action
via `BatchIngestionService`. Covered by `tests/test_pipeline.py` (14 passing)
and `tests/test_batch.py` (SQLite → Neo4j flow, `test_cli_ingest_command`).
Note: this issue was written against a `playground.py` `run` action; the code
landed as the `ingest` action in `src/knowledge_map/cli/main.py`. Relabeled
`completed`.
