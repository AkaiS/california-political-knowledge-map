Status: ready-for-human

# Issue 1: CLI Setup and Neo4j Database Clear Action

## Parent

- [PRD.md](file:///Users/akaisenghor/Projects/california-political-knowledge-map/.scratch/influence-graph-playground/PRD.md)

## What to build

Create the base structure of the command-line interface `playground.py` that serves as the execution entrypoint. Implement a subcommand or action `clear` that resets the Neo4j database.

The implementation must:
- Load credentials from environment variables (`NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD`).
- Initialize a connection driver to the target Neo4j instance.
- Execute a query to delete all nodes and relationships from the database (e.g., `MATCH (n) DETACH DELETE n`).
- Wrap the execution in robust error-handling logic and output user-friendly status/error messages.
- Provide a unit testing seam (e.g., accepting a mock driver/session object) and tests verifying connection failure, session creation, and transaction query executions.

Avoid hardcoding configuration values.

## Acceptance criteria

- [x] Command line router supports executing `python playground.py clear` successfully.
- [x] Reset query runs inside a write transaction and deletes all nodes and relationships.
- [x] Missing or invalid database credentials in `.env` raise clean, informative error messages instead of raw tracebacks.
- [x] Unit tests mock the Neo4j driver/session and verify the correct deletion Cypher query is executed.

## Blocked by

None - can start immediately
