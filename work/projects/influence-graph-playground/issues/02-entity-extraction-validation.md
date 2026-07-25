Labels: completed

# Issue 2: Extraction Prompts, Pydantic Validation, and Pydantic AI Integration

## Parent

- [PRD.md](file:///Users/akaisenghor/Projects/california-political-knowledge-map/work/projects/influence-graph-playground/PRD.md)

## What to build

Create the prompt-based entity extraction and validation layers. This consists of:
- Creating `extraction_prompt.txt` at the repository root with prompt guidelines for extracting entities (e.g., PoliticalActor, Organization, PublicPolicyMeasure) and their relationships from news stories.
- Defining Pydantic v2 schemas for extracted data models (e.g., `Node`, `Relationship`, `ExtractionResult`).
- Implementing a Pydantic AI Agent configured with `output_type=ExtractionResult` and instructions loaded from `extraction_prompt.txt`.
- Configuring the agent model to talk to the local Ollama instance (targeting `gemma:31b` via an OpenAI-compatible model layer utilizing the `OLLAMA_BASE_URL` configuration from `.env`).
- Adding a CLI dry-run capability (e.g., `python playground.py run --dry-run` or similar) that parses a sample article or text, runs the Pydantic AI agent, and displays the validated results without performing Neo4j write operations.
- Setting up unit tests using Pydantic AI's built-in `TestModel` or `FunctionModel` to mock agent execution and verify parsing, validation error handling, and offline pipeline correctness.

## Acceptance criteria

- [x] `extraction_prompt.txt` is loaded dynamically from the root and supplied as instructions to the agent.
- [x] Pydantic v2 models validate node names, node labels, relationship sources, targets, types, and dynamic metadata fields.
- [x] Command line dry-run runs successfully and outputs validated JSON from the Pydantic AI agent.
- [x] Unit tests assert that the prompt is correctly assembled and mock agent executions correctly validate correct structures and handle validation failures gracefully via the testing models.

## Blocked by

None
