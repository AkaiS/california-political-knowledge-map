# 0002. Story Pipeline Architecture

We decided to encapsulate the orchestration of our text processing flow (coreference resolution, chunking, embedding generation, entity extraction, and persistence) within a synchronous `StoryPipeline` coordinator class. This coordinator uses dependency-injected python `Protocol` adapters (`DatabaseAdapter`, `EmbeddingAdapter`, `CoreferenceAdapter`, `EntityExtractionAdapter`), allowing the entire ingestion process to be testable via mocks and configured for dry runs that bypass database ingestion.

## Considered Options

* **Direct Procedural Script Ingestion**: Leaving orchestration in `playground.py`. While simple, it prevents unit testing the flow without spinning up database connections or mocking global imports.
* **Synchronous vs Asynchronous Orchestration**: We chose synchronous orchestration for the coordinator because the pipeline's overall structure is a linear sequence of steps where each phase depends entirely on the output of the previous phase. Any internal async operations (such as fetching embeddings) are encapsulated inside the adapters themselves using `asyncio.run()`.
* **Adapters accepting Domain Models**: We chose to have adapter signatures accept strongly-typed Pydantic domain models (e.g. `SourceArticle`, `ArticleChunk`) rather than raw primitives, ensuring strong boundary validation and clear domain-level interfaces.

## Consequences

* **Testability**: The pipeline can be fully unit-tested with lightweight mock adapters.
* **Separation of Concerns**: The database adapter, coreference resolution, embedding manager, and entity extraction logic are decoupled and only linked via the pipeline orchestration protocols.
* **Maintainability**: Adding new pipeline steps or changing step implementations only requires modifying the specific adapter module or updating the thin coordinator logic.
