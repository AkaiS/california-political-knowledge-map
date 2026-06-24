Status: ready-for-agent

# PRD: CA Political Influence GraphRAG Engine - Entity Extraction and Semantic Similarity Playground

## Problem Statement

As a developer, I need to evaluate and iterate on LLM prompts for extracting entities and relationships from California political news stories, ingest them into a dockerized Neo4j database, and programmatically analyze the schema (node labels) and semantic similarity of nodes to handle entity resolution and duplicate detection. Currently, doing this manually or piece-by-piece across multiple articles is inefficient, and we need a systematic way to evaluate prompt performance across the entire extracted knowledge graph.

## Solution

Build `playground.py`, a dedicated command-line interface that reads scraped news articles (Source Articles) from the local SQLite database, utilizes a local Ollama instance (running `gemma:31b`) with a prompt loaded from an external file (`extraction_prompt.txt`) to extract nodes and relationships, validates the data using Pydantic v2 schemas, and saves them directly to Neo4j. The script will also calculate node name embeddings via Ollama (using the `embeddinggemma` model) to detect semantically similar nodes (similarity > 0.85) within the same labels, and provide a utility to clear the database for rapid iteration.

## User Stories

1. As a developer, I want to edit `extraction_prompt.txt` so that I can modify the LLM's entity extraction guidance without changing any application code.
2. As a developer, I want to run the pipeline on all Source Articles in the SQLite database so that I can build a complete knowledge graph from the full dataset.
3. As a developer, I want the LLM's extracted JSON payload to be parsed and validated using Pydantic v2 schemas so that malformed data is rejected before writing to Neo4j.
4. As a developer, I want the extracted entities and relationships to be saved directly to my dockerized Neo4j instance so that I can query and view the resulting graph.
5. As a developer, I want to run a command/flag that clears all nodes and relationships in the Neo4j instance so that I can start fresh when testing a new prompt version.
6. As a developer, I want to query the current node labels present in the Neo4j database so that I can inspect the generated ontology.
7. As a developer, I want to compute name embeddings using `embeddinggemma` via Ollama and automatically identify pairs of nodes within the same label that have a cosine similarity above 0.85 so that I can flag potential duplicates for Entity Resolution.

## Implementation Decisions

### Modules & Configuration
- **Script**: A new script `playground.py` that serves as the entry point for running the extraction, loading prompt configurations, executing Cypher queries, and calculating embeddings.
- **Prompt Source**: `extraction_prompt.txt` at the repository root.
- **Data Validation**: Pydantic v2 schemas to define nodes (name, label, properties) and relationships (source, target, type, properties).
- **Graph Database Client**: Neo4j Python client configured via `.env` credentials (`NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD`).
- **Embedding Client**: Local Ollama HTTP or client wrapper calling the `/api/embeddings` or `/api/embed` endpoint with the `embeddinggemma` model.

### Neo4j Schema
- Extraction results will map to custom node labels (e.g., `PoliticalActor`, `Organization`, `PublicPolicyMeasure`) and custom relationship types dynamically defined by the extraction prompt.
- Nodes will also contain properties such as `name` and `source_url`.

### CLI Interface
The `playground.py` script will support different actions, for example:
- `python playground.py run`: Run entity extraction across all articles and write to Neo4j.
- `python playground.py clear`: Reset/clear the Neo4j database.
- `python playground.py analyze`: List all node labels and output pairs of nodes within each label with cosine similarity > 0.85 based on `embeddinggemma` embeddings.

## Testing Decisions

### Seams for Testing
To ensure the playground is testable, we will implement testing at the following boundaries (seams):
- **Ollama API Seam**: The function calling local Ollama (`extract_entities_from_text` and `get_embedding`) will accept an optional API client/url parameter or respect standard request mocking, allowing us to mock LLM extraction payloads and embedding vectors.
- **Database Ingestion Seam**: The Neo4j ingestion layer will be structured as isolated functions that take Neo4j drivers/sessions, permitting us to mock database writes and test the exact Cypher query structures generated.
- **Cosine Similarity Seam**: A pure helper function for computing cosine similarity between two float vectors, allowing us to unit test the similarity logic without hitting live databases or models.

### Test Coverage
- Unit tests will assert Pydantic model validation of raw extraction outputs (validating edge cases of missing properties, empty names, or invalid relation links).
- Tests will verify that the similarity logic correctly groups close pairs and ignores distant pairs.

## Out of Scope
- Automated web crawling or scraping during playground runs (relies on the pre-existing SQLite articles database).
- An interactive web or graphic frontend.
- Entity resolution merges (highlighting/reporting duplicates is in-scope; automatically merging them is out-of-scope for this phase).

## Further Notes
- Ollama connections will utilize the `OLLAMA_BASE_URL` defined in `.env`.
