"""Install the local databases and their checked-in schema."""

import os
from collections.abc import Iterator
from pathlib import Path

from dotenv import load_dotenv
from neo4j import Driver, GraphDatabase

from knowledge_map.adapters.sqlite_db import DEFAULT_DB_PATH, init_db

PROJECT_ROOT = Path(__file__).resolve().parents[2]
NEO4J_SCHEMA_DIRECTORY = PROJECT_ROOT / "schema" / "neo4j"


def cypher_statements(text: str) -> Iterator[str]:
    """Yield statements from a repository-owned Cypher schema file."""

    for statement in text.split(";"):
        statement = statement.strip()
        if statement:
            yield statement


def apply_neo4j_schema(
    driver: Driver,
    *,
    database: str,
    schema_directory: Path = NEO4J_SCHEMA_DIRECTORY,
) -> tuple[Path, ...]:
    """Apply every checked-in Neo4j schema file in filename order."""

    paths = tuple(sorted(schema_directory.glob("*.cypher")))
    if not paths:
        raise FileNotFoundError(f"No Neo4j schema files found in {schema_directory}")

    with driver.session(database=database) as session:
        for path in paths:
            for statement in cypher_statements(path.read_text()):
                session.run(statement).consume()
    return paths


def _required_environment(name: str) -> str:
    value = os.environ.get(name)
    if value is None or not value.strip():
        raise ValueError(f"{name} environment variable is missing or empty.")
    return value


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env")

    uri = _required_environment("NEO4J_URI")
    username = _required_environment("NEO4J_USERNAME")
    password = _required_environment("NEO4J_PASSWORD")
    database = os.environ.get("NEO4J_DATABASE", "neo4j")
    sqlite_path = Path(os.environ.get("SQLITE_DB_PATH", DEFAULT_DB_PATH))
    if not sqlite_path.is_absolute():
        sqlite_path = PROJECT_ROOT / sqlite_path

    init_db(str(sqlite_path))
    print(f"SQLite schema ready: {sqlite_path}")

    with GraphDatabase.driver(uri, auth=(username, password)) as driver:
        driver.verify_connectivity()
        paths = apply_neo4j_schema(driver, database=database)

    for path in paths:
        print(f"Applied Neo4j schema: {path.relative_to(PROJECT_ROOT)}")
    print(f"Neo4j indexes ready: {database} at {uri}")


if __name__ == "__main__":
    main()
