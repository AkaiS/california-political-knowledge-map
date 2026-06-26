# 0001. Article Chunking and Coreference Resolution in Neo4j

We decided to process Source Articles by first running an LLM-based Coreference Resolution step (using XML tag markup and a Critic LLM validation loop), resolving the tags to plain text in Python, and recursively splitting the article into Article Chunks (with 10% overlap, configured via environment variables). We will save the Article Chunks in Neo4j as first-class `(:Chunk)` nodes with embeddings, linked structurally to `(:Article)` nodes and to extracted entities via `[:MENTIONED_IN]` relationships, with a Neo4j vector index created on the chunk embeddings.

## Considered Options

* **Neo4j Provenance**: Properties on nodes/edges vs explicit `(:Article)` and `(:Chunk)` nodes. We chose explicit nodes to enable clean structural queries and vector search traversal.
* **Coreference Resolution**: Local NLP libraries vs LLM-based tagging. We chose LLM-based tagging with XML tags (`<ref>`) and a self-correcting Critic loop for higher semantic accuracy on complex political texts.
* **Tag Resolution**: Keeping XML tags in chunks vs resolving them to clean plain text. We chose resolving them to plain text to optimize embedding generation and downstream entity extraction.
