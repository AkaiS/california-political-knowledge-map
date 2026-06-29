Status: ready-for-agent

## Parent

[.scratch/story-pipeline-coordinator/PRD.md](file:///Users/akaisenghor/Projects/california-political-knowledge-map/.scratch/story-pipeline-coordinator/PRD.md)

## What to build

Define the pipeline's core Pydantic domain models (`SourceArticle` and `PipelineResult`) in `schemas/`, and the four boundary protocols (`DatabaseAdapter`, `EmbeddingAdapter`, `CoreferenceAdapter`, and `EntityExtractionAdapter`) inside `pipeline.py`. 

Implement the `StoryPipeline` coordinator class in `pipeline.py`. It should orchestrate the steps (coreference -> chunking -> embedding -> extraction -> persistence) using the injected protocols. Under `dry_run=True`, it must skip database persistence and return a populated `PipelineResult` object. 

Create a comprehensive unit test suite that tests the coordinator's flow, logging, and dry-run branching by injecting lightweight mocks conforming to the defined protocols.

## Acceptance criteria

- [ ] `SourceArticle` and `PipelineResult` Pydantic models are defined in `schemas/` and exported via `schemas/__init__.py`.
- [ ] `DatabaseAdapter`, `EmbeddingAdapter`, `CoreferenceAdapter`, and `EntityExtractionAdapter` python `Protocol`s are defined in `pipeline.py`.
- [ ] `StoryPipeline` coordinator class is defined in `pipeline.py` and accepts the four protocols in its constructor.
- [ ] `StoryPipeline.run()` implements the correct sequential flow: Coreference -> Chunking -> Embedding -> Extraction -> Ingestion.
- [ ] Under `dry_run=True`, `StoryPipeline.run()` returns a structured `PipelineResult` and does not call any database adapter method.
- [ ] Unit tests verify end-to-end execution, logging, and error handling of `StoryPipeline` using mock adapters.

## Blocked by

None - can start immediately
