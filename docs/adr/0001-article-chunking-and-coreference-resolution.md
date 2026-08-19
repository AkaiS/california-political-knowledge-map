# 0001. Article Chunking and Coreference Resolution in Neo4j

> **Coreference portion superseded by [ADR 0016](0016-mention-spans-for-coreference-resolution.md).** The XML-markup and tag-resolution choices recorded below are historical. The decision to recursively split Source Articles into Article Chunks (with 10% overlap, configured via environment variables) and to save them in Neo4j as first-class `(:Chunk)` nodes with embeddings, linked structurally to `(:Article)` nodes and to extracted entities via `[:MENTIONED_IN]` relationships, with a Neo4j vector index created on the chunk embeddings, remains in force.

At the time this decision was recorded, we processed Source Articles with an
LLM-based Coreference Resolution step and then recursively split the resolved
text into Article Chunks. The coreference mechanism has since been replaced as
described by ADR 0016; the chunking and Neo4j decisions in this ADR remain
unchanged.

## Considered Options

* **Neo4j Provenance**: Properties on nodes/edges vs explicit `(:Article)` and `(:Chunk)` nodes. We chose explicit nodes to enable clean structural queries and vector search traversal.
* **Coreference Resolution** *(superseded by ADR 0016)*: Local NLP libraries vs an LLM-based resolution step. The original choice used XML tags and a self-correcting Critic loop for higher semantic accuracy on complex political texts.
* **Tag Resolution** *(superseded by ADR 0016)*: Keeping XML tags in chunks vs resolving them to clean plain text. The original choice resolved them to plain text to optimize embedding generation and downstream entity extraction.
