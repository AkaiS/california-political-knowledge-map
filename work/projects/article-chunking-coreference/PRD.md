# Product Requirements: Article Chunking and Coreference Resolution

Labels: completed

## Problem Statement

When performing entity and relationship extraction on long news articles (Source Articles), feeding the entire text to the language model causes two main issues:
1. Large context sizes reduce the LLM's accuracy and lead to missed entities or relationships (referred to as the "lost in the middle" effect).
2. It is impossible to generate precise vector embeddings for long articles to perform semantic search at a granular level.

However, splitting the text into smaller chunks directly introduces new problems:
1. Pronouns (e.g. "he", "they", "the governor") in later chunks lose their references to entities introduced in earlier chunks, leading to corrupted or missing extractions.
2. We lose the exact provenance (which specific sentence or chunk supported a relationship).

## Solution

We will build a pipeline that:
1. Preprocesses the **Source Article** text with a **Coreference Resolution** LLM agent to tag vague pronouns with `<ref entity='Entity Name'>pronoun</ref>` tags.
2. Validates annotations using a **Coreference Critic** LLM agent with a self-correcting feedback loop.
3. Resolves the tags to plain text (replacing pronouns with canonical entity names) before chunking.
4. Splits the clean, resolved text into **Article Chunks** using Chonkie's `RecursiveChunker` and `OverlapRefinery` (character-based, with 10% overlap).
5. Runs **Entity Extraction** independently on each chunk.
6. Ingests the Article Chunks, Articles, and entities into Neo4j with structural relationships, vector embeddings, and a vector index.

---

## User Stories

1. As a developer running the playground, I want long articles to be processed in smaller chunks so that the entity extraction quality is significantly improved.
2. As a data analyst querying the influence graph, I want to see explicit `(:Article)` and `(:Chunk)` nodes in Neo4j so that I can trace exactly which parts of an article supported a relationship.
3. As a developer, I want coreferences in the article to be resolved using an LLM before chunking, so that pronouns in later chunks are correctly identified as the canonical entities.
4. As a developer, I want a Critic LLM to validate the coreference tagging, so that incorrect reference mappings are caught and corrected before chunking.
5. As a database administrator, I want chunk embeddings to be indexed in Neo4j, so that I can run high-performance similarity searches over specific article segments.
6. As a developer, I want to configure the chunk size and overlap percentage via environment variables, so that I can tune the pipeline's behavior without modifying the code.

---

## Implementation Decisions

### Coreference Resolution Module
- **Annotator Agent**: A Pydantic AI agent that reads the text of a Source Article and returns an Annotated Article containing XML tags wrapping pronouns (e.g., `<ref entity='Gavin Newsom'>he</ref>`).
- **Critic Agent**: A Pydantic AI agent that evaluates the Annotated Article. If it finds incorrect or hallucinated references, it returns specific error feedback.
- **Correction Loop**: A Python wrapper that runs the Annotator, passes the result to the Critic, and if the Critic rejects, feeds the Critic's errors back to the Annotator for a corrected pass (up to 3 retries max before falling back to the original text).
- **Tag Substitution**: A Python helper that processes the approved Annotated Article and replaces every `<ref entity="Entity Name">pronoun</ref>` tag with `Entity Name`, producing clean plain text for downstream chunking.

### Chunking Module
- **Chonkie-based Chunking**: Splits the resolved text recursively using `chonkie.RecursiveChunker` (hierarchical splitting with delimiters like paragraphs, sentences, and words) and `chonkie.OverlapRefinery` (for prefix overlap).
- **Configurable Parameters**: Reads `CHUNK_SIZE` and `CHUNK_OVERLAP_PCT` (defaults to 1000 characters and 0.10 or 10% overlap) from the environment (`.env`).

### Neo4j Graph Database Integration
- **Article Nodes**: Creates `(:Article)` nodes uniquely identified by `url`, setting properties `title`, `author`, and `published_date`.
- **Chunk Nodes**: Creates `(:Chunk)` nodes uniquely identified by `id` (e.g. `url + "#chunk_" + index`), setting `text`, `chunk_index`, and `embedding` (array of floats).
- **Structural Links**: Connects each chunk to its article: `(Chunk)-[:BELONGS_TO]->(Article)`.
- **Entity Provenance**: Connects extracted entities to the chunk they appeared in: `(Entity)-[:MENTIONED_IN]->(Chunk)`.
- **Relationship Provenance**: Sets a `source_chunk_id` property on the relationship edge between extracted entities to trace it back to the specific chunk.
- **Vector Index**: Automatically creates a Neo4j Vector Index (named `chunk_vector_index`) on the `embedding` property of the `(:Chunk)` label if it does not exist.

---

## Testing Decisions

### Seams for Testing
1. **Coreference Seam**: Test the coreference resolution, critic check, and self-correction loop in isolation by mocking the LLM responses.
2. **Splitting Seam**: Test the Chonkie-based chunking configuration with various inputs to verify that chunk sizes and the 10% overlap are correctly applied, without invoking any LLMs or databases.
3. **Graph Ingestion Seam**: Test the Neo4j ingestion function using mock database transactions to verify that the generated Cypher queries create the correct `(:Article)`, `(:Chunk)`, and `[:MENTIONED_IN]` / `[:BELONGS_TO]` structures, and that relationship edges receive the `source_chunk_id` property.

### Prior Art
- `tests/test_extraction.py` provides examples of mocking Pydantic AI agent LLM calls using `FunctionModel`.
- `tests/test_playground.py` contains examples of mocking Neo4j driver sessions and transactions to verify Cypher execution queries.

---

## Out of Scope
- Implementing coreference resolution for images or non-textual attachments.
- Advanced entity resolution during the chunking phase (relying on downstream entity resolution processes already defined).
- Persistent caching of coreference resolution output outside of Neo4j.
