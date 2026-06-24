Status: ready-for-agent

# Issue 2: Extraction Prompts, Pydantic Validation, and Ollama Extraction Integration

## Parent

- [PRD.md](file:///Users/akaisenghor/Projects/california-political-knowledge-map/.scratch/influence-graph-playground/PRD.md)

## What to build

Create the prompt-based entity extraction and validation layers. This consists of:
- Creating `extraction_prompt.txt` at the repository root with prompt guidelines for extracting entities (e.g., PoliticalActor, Organization, PublicPolicyMeasure) and their relationships from news stories.
- Defining Pydantic v2 schemas for extracted data models (e.g., `Node`, `Relationship`, `ExtractionResult`).
- Implementing local Ollama API caller using HTTP requests (targeting the `gemma:31b` model and utilizing the `OLLAMA_BASE_URL` configuration from `.env`).
- Parsing raw LLM JSON outputs and validating them using the Pydantic models.
- Adding a CLI dry-run capability (e.g., `python playground.py run --dry-run` or similar) that parses a sample article or text, calls the extraction pipeline, and displays the validated results without performing Neo4j write operations.
- Providing an Ollama API mock seam to verify request payloads, handle empty/malformed LLM responses, and run unit tests offline.

## Acceptance criteria

- [ ] `extraction_prompt.txt` is loaded dynamically from the root.
- [ ] Pydantic v2 models validate node names, node labels, relationship sources, targets, types, and dynamic metadata fields.
- [ ] Command line dry-run runs successfully and outputs validated JSON.
- [ ] Unit tests assert that the prompt is correctly assembled, Ollama request/response parsing works, and invalid JSON structures are rejected gracefully.

## Blocked by

None
