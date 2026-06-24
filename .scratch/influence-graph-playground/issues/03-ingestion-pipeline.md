Status: ready-for-agent

# Issue 3: End-to-End SQLite to Neo4j Ingestion Command

## Parent

- [PRD.md](file:///Users/akaisenghor/Projects/california-political-knowledge-map/.scratch/influence-graph-playground/PRD.md)

## What to build

Implement the ingestion pipeline that coordinates loading stories from SQLite, executing entity extraction, and inserting the graph data into Neo4j:
- Extend `db.py` to retrieve all news articles (`get_all_stories` or query equivalent) containing the parsed content.
- Update `playground.py run` to fetch these stories, loop through them, run the validation extraction (developed in Issue 2), and build transactions to write nodes and relationships to Neo4j.
- Neo4j node insertion must use `MERGE` statements parameterized by node labels and names to ensure idempotency. Include properties such as `name` and `source_url`.
- Relationship insertion must match the corresponding source and target nodes by name and label, and run `MERGE` for the relationship type.
- Implement an ingestion seam where database writes can be tested with isolated mock sessions, and unit test the exact Cypher query logic generated.

## Acceptance criteria

- [ ] Command line action `python playground.py run` runs successfully over all articles in SQLite.
- [ ] Nodes are inserted idempotently into Neo4j (no duplicates are created for the same name and label on repeated runs).
- [ ] Relationships link the correct nodes and are written idempotently.
- [ ] Unit tests verify the end-to-end integration: querying SQLite, iterating through records, executing mocked Pydantic AI agent runs, and calling Neo4j drivers with the correct Cypher statements.

## Blocked by

- [Issue 1: CLI Setup and Neo4j Database Clear Action](file:///Users/akaisenghor/Projects/california-political-knowledge-map/issues/01-neo4j-clear.md)
- [Issue 2: Extraction Prompts, Pydantic Validation, and Pydantic AI Integration](file:///Users/akaisenghor/Projects/california-political-knowledge-map/issues/02-entity-extraction-validation.md)

## Comments

- **2026-06-24**: Implemented and verified via `/tdd`. All 28 tests pass successfully.
