Status: ready-for-agent

## Parent

[.scratch/story-pipeline-coordinator/PRD.md](file:///Users/akaisenghor/Projects/california-political-knowledge-map/.scratch/story-pipeline-coordinator/PRD.md)

## What to build

Align `Neo4jAdapter` in `graph_db.py` to conform to `DatabaseAdapter`, accepting `SourceArticle` and `ArticleChunk` Pydantic models directly instead of raw primitive parameters.

Refactor `playground.py` (and any other entrypoints) to instantiate the concrete adapters, inject them into `StoryPipeline`, and invoke `run()`. Remove the deprecated procedural `process_story` and associated helper logic from the CLI playground script.

## Acceptance criteria

- [ ] `Neo4jAdapter` methods conform to `DatabaseAdapter` protocol signatures, accepting `SourceArticle` and `ArticleChunk` models.
- [ ] Direct dependency imports on embedding clients or extraction details are removed from `playground.py`.
- [ ] `playground.py` instantiates `StoryPipeline` with concrete adapter dependencies.
- [ ] Refactored CLI commands (`run` and `run --dry-run`) execute successfully, verifying the entire end-to-end flow.
- [ ] Integration tests verify the connection between `StoryPipeline` and the refactored database adapter.

## Blocked by

- [.scratch/story-pipeline-coordinator/issues/02-concrete-in-process-adapters.md](file:///Users/akaisenghor/Projects/california-political-knowledge-map/.scratch/story-pipeline-coordinator/issues/02-concrete-in-process-adapters.md)
