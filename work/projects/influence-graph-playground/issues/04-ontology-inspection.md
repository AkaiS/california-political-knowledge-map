Labels: completed

# Issue 4: Ontology Node Labels Inspection Command

## Parent

- [PRD.md](file:///Users/akaisenghor/Projects/california-political-knowledge-map/work/projects/influence-graph-playground/PRD.md)

## What to build

Implement a query mechanism to inspect the generated ontology:
- Implement a query to Neo4j that retrieves all distinct node labels present in the current database state (e.g., using `CALL db.labels()`).
- Add/expose this behavior inside the `analyze` subcommand of `playground.py` (e.g., printing a clean, ordered list of labels).
- Provide unit tests that mock the database session response and assert correct parsing and formatting of the labels list.

## Acceptance criteria

- [x] Command line action `python playground.py analyze` prints a list of distinct node labels in the Neo4j database.
- [x] Retrieval query functions correctly and prints empty or graceful messages when no labels exist.
- [x] Unit tests cover database query execution and formatting of node labels from Neo4j session responses.

## Blocked by

- [Issue 1: CLI Setup and Neo4j Database Clear Action](file:///Users/akaisenghor/Projects/california-political-knowledge-map/work/projects/influence-graph-playground/issues/01-neo4j-clear.md)
- [Issue 3: End-to-End SQLite to Neo4j Ingestion Command](file:///Users/akaisenghor/Projects/california-political-knowledge-map/work/projects/influence-graph-playground/issues/03-ingestion-pipeline.md)
