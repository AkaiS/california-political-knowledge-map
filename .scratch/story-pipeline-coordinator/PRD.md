# Product Requirements: Story Pipeline Coordinator

Status: ready-for-agent

## Problem Statement

Currently, the orchestration of coreference resolution, text cleanup, chunk splitting, embedding calculations, and database ingestion is implemented procedurally inside the CLI module (`playground.py`). This procedural implementation causes several issues:
1. **Testing Friction**: It is difficult to unit test the pipeline flow and coordinate steps without spinning up actual database connections or mocking global functions and module imports.
2. **High Coupling**: The CLI script is tightly coupled to the database driver, embedding client, and agent configurations, making the system fragile and hard to reuse in other parts of the codebase (e.g., crawler, web endpoints).
3. **Leaky Dry-Runs**: Dry-run logic is scattered within procedural checks and print statements, preventing a clean programmatic way to execute the pipeline and inspect outputs structured in-memory.

## Solution

We will build a decoupled pipeline orchestration layer by:
1. Defining a strongly-typed `SourceArticle` Pydantic model for the input data.
2. Introducing formal python `Protocol`s representing the boundary interfaces (**Ports**): `DatabaseAdapter`, `EmbeddingAdapter`, `CoreferenceAdapter`, and `EntityExtractionAdapter`.
3. Creating a synchronous, thin `StoryPipeline` coordinator class that orchestrates the flow through these injected adapters.
4. Implementing a structured `PipelineResult` Pydantic model returned at the end of the pipeline execution (especially during dry runs).
5. Defining concrete implementations for these adapters in their respective modules (`graph_db.py`, `embedding.py`, `coreference.py`, `extraction.py`).

---

## User Stories

1. As a developer, I want to execute the end-to-end ingestion pipeline using a single class call, so that I can process news articles with a unified, clean interface.
2. As a developer, I want to inject mock adapter implementations into the pipeline coordinator, so that I can easily unit test the pipeline's branching and error handling without actual database or API dependencies.
3. As a developer running the playground CLI, I want to run a dry-run of the ingestion pipeline that returns a structured result object, so that I can programmatically verify the extraction output before saving it to Neo4j.
4. As a developer, I want the embedding adapter to handle vector dimension validation internally, so that the pipeline coordinator is not cluttered with mathematical constraints.
5. As an operator, I want the pipeline coordinator to output log statements indicating progress at each stage, so that I can track execution during long-running ingestion tasks.

---

## Implementation Decisions

### Domain Schemas
- **`SourceArticle`**: A Pydantic model containing metadata (`url`, `title`, `author`, `published_date`) and `content`.
- **`PipelineResult`**: A Pydantic model capturing the outcome of a pipeline execution, including the resolved text, list of chunks, their generated embeddings, and the extracted entities/relationships.

### Adapter Protocols (Ports)
- **`DatabaseAdapter`**: Protocol defining:
  - `ingest_article(article: SourceArticle) -> None`
  - `ingest_chunk(article: SourceArticle, chunk: ArticleChunk, embedding: list[float]) -> None`
  - `ingest_chunk_extraction(chunk_id: str, extraction: ExtractionResult) -> None`
- **`EmbeddingAdapter`**: Protocol defining:
  - `process_chunks(chunks: list[ArticleChunk]) -> list[list[float]]` (computes and validates embeddings).
- **`CoreferenceAdapter`**: Protocol defining:
  - `resolve(content: str) -> str` (resolves pronouns to canonical entities).
- **`EntityExtractionAdapter`**: Protocol defining:
  - `extract(chunk_text: str) -> ExtractionResult` (runs LLM extraction over chunk text).

### Ingestion Coordinator
- **`StoryPipeline` Class**: Created in `pipeline.py`, initialized with the four adapter dependencies.
- **Synchronous Run**: Implements `run(article: SourceArticle, dry_run: bool = False) -> Optional[PipelineResult]`. 
- **Branching Decision**: If `dry_run` is True, it processes the article and returns the structured `PipelineResult` but skips all `DatabaseAdapter` calls. If False, it persists the article, chunks, and extractions using the database adapter.

---

## Testing Decisions

### Seams for Testing
1. **Pipeline Seam**: The highest seam for testing is the `StoryPipeline` class itself. By injecting lightweight mock adapters conforming to the defined Protocols, we can verify the execution order, the branching logic under `dry_run=True` / `dry_run=False`, error handling, and the structure of the returned `PipelineResult` without making any database connections or network API requests.

### Prior Art
- `tests/test_playground.py` demonstrates mock setup for the database adapter interactions.
- `tests/test_extraction.py` shows how to mock Pydantic AI models.

---

## Out of Scope
- Creating an asynchronous queue worker or multi-process pipeline runner (which remains a future enhancement).
- Designing interactive user refinement of the entity schema inside the coordinator itself (which is owned by the CLI presentation layer).
- Modifying the text chunker interface itself (it remains managed via the `chunking.py` wrapper).

---

## Further Notes
- The concrete adapters will be defined in their respective modules to keep code co-located with their technical dependencies.
