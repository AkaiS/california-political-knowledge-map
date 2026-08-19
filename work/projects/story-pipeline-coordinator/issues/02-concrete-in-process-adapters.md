Labels: completed

## Parent

[.scratch/story-pipeline-coordinator/PRD.md](file:///Users/akaisenghor/Projects/california-political-knowledge-map/work/projects/story-pipeline-coordinator/PRD.md)

## What to build

Implement concrete classes conforming to the `EmbeddingAdapter`, `CoreferenceAdapter`, and `EntityExtractionAdapter` protocols in their respective modules:
1. `EmbeddingAdapter` implementation in `embedding.py` that processes chunks (including dimension verification against configuration).
2. `CoreferenceAdapter` implementation in `coreference.py` that runs Mention Span resolution and returns resolved text.
3. `EntityExtractionAdapter` implementation in `extraction.py` that wraps the `extract_entities` logic.

Verify these concrete adapters function correctly within our pipeline tests by using mock LLM models and embedders.

## Acceptance criteria

- [x] `EmbeddingAdapter` is implemented in `embedding.py`, conforming to the protocol, and includes dimension check validation against `settings.embedding.dimension`.
- [x] `CoreferenceAdapter` is implemented in `coreference.py`, conforming to the protocol, and executes Mention Span resolution.
- [x] `EntityExtractionAdapter` is implemented in `extraction.py`, conforming to the protocol, and runs extraction over text chunks.
- [x] Pipeline tests are updated to integrate concrete adapters, mocking only the underlying OpenAI/Ollama LLM responses.

## Blocked by

- [.scratch/story-pipeline-coordinator/issues/01-pipeline-interface-and-mock-coordinator.md](file:///Users/akaisenghor/Projects/california-political-knowledge-map/work/projects/story-pipeline-coordinator/issues/01-pipeline-interface-and-mock-coordinator.md)
