Status: ready-for-agent

## Parent

[.scratch/story-pipeline-coordinator/PRD.md](file:///Users/akaisenghor/Projects/california-political-knowledge-map/.scratch/story-pipeline-coordinator/PRD.md)

## What to build

Implement concrete classes conforming to the `EmbeddingAdapter`, `CoreferenceAdapter`, and `EntityExtractionAdapter` protocols in their respective modules:
1. `EmbeddingAdapter` implementation in `embedding.py` that processes chunks (including dimension verification against configuration).
2. `CoreferenceAdapter` implementation in `coreference.py` that wraps the `resolve_coreferences` and `replace_tags_with_entities` functions.
3. `EntityExtractionAdapter` implementation in `extraction.py` that wraps the `extract_entities` logic.

Verify these concrete adapters function correctly within our pipeline tests by using mock LLM models and embedders.

## Acceptance criteria

- [ ] `EmbeddingAdapter` is implemented in `embedding.py`, conforming to the protocol, and includes dimension check validation against `settings.embedding.dimension`.
- [ ] `CoreferenceAdapter` is implemented in `coreference.py`, conforming to the protocol, and executes pronoun resolution and cleanup.
- [ ] `EntityExtractionAdapter` is implemented in `extraction.py`, conforming to the protocol, and runs extraction over text chunks.
- [ ] Pipeline tests are updated to integrate concrete adapters, mocking only the underlying OpenAI/Ollama LLM responses.

## Blocked by

- [.scratch/story-pipeline-coordinator/issues/01-pipeline-interface-and-mock-coordinator.md](file:///Users/akaisenghor/Projects/california-political-knowledge-map/.scratch/story-pipeline-coordinator/issues/01-pipeline-interface-and-mock-coordinator.md)
