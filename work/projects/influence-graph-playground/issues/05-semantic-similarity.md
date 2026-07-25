Labels: completed

# Issue 5: Cosine Similarity Duplicate Identification via Ollama Embeddings

## Parent

- [PRD.md](file:///Users/akaisenghor/Projects/california-political-knowledge-map/work/projects/influence-graph-playground/PRD.md)

## What to build

Implement the semantic similarity analysis to support Entity Resolution:
- Configure a Pydantic AI `Embedder` (e.g., using an OpenAI-compatible model target configured to point to local Ollama) utilizing the `embeddinggemma` model.
- Write a pure helper function to calculate the cosine similarity between two float vectors.
- Query Neo4j to retrieve all nodes, grouping them by their label.
- For all nodes within each label, compute name embeddings via the Pydantic AI `Embedder`.
- Calculate cosine similarity pairwise for all nodes sharing a label.
- Output pairs with similarity > 0.85 to the terminal under the `analyze` CLI subcommand to identify potential duplicates.
- Ensure the embedding and similarity steps can be fully mocked for unit testing, avoiding any live server requirements.

## Acceptance criteria

- [x] Command line action `python playground.py analyze` generates embeddings and displays a list of potential duplicate node pairs with similarity scores > 0.85.
- [x] Calculations are isolated to pairs of nodes with matching labels.
- [x] Cosine similarity helper is covered by unit tests verifying correct mathematical results.
- [x] Offline unit tests mock the Pydantic AI `Embedder` and the Neo4j database node queries, verifying that the analyzer identifies the correct candidate duplicate pairs.

## Blocked by

- [Issue 1: CLI Setup and Neo4j Database Clear Action](file:///Users/akaisenghor/Projects/california-political-knowledge-map/work/projects/influence-graph-playground/issues/01-neo4j-clear.md)
- [Issue 3: End-to-End SQLite to Neo4j Ingestion Command](file:///Users/akaisenghor/Projects/california-political-knowledge-map/work/projects/influence-graph-playground/issues/03-ingestion-pipeline.md)
