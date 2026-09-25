from pathlib import Path
from unittest.mock import MagicMock

import pytest

from knowledge_map.database_setup import (
    NEO4J_SCHEMA_DIRECTORY,
    apply_neo4j_schema,
    cypher_statements,
)


def test_cypher_statements_skips_empty_segments():
    assert tuple(cypher_statements("RETURN 1;\n; RETURN 2;")) == (
        "RETURN 1",
        "RETURN 2",
    )


def test_apply_neo4j_schema_runs_files_in_order(tmp_path: Path):
    (tmp_path / "002_second.cypher").write_text("RETURN 2;")
    (tmp_path / "001_first.cypher").write_text("RETURN 1; RETURN 1.5;")
    driver = MagicMock()
    session = driver.session.return_value.__enter__.return_value

    paths = apply_neo4j_schema(
        driver, database="knowledge-map", schema_directory=tmp_path
    )

    assert [path.name for path in paths] == ["001_first.cypher", "002_second.cypher"]
    driver.session.assert_called_once_with(database="knowledge-map")
    assert [call.args[0] for call in session.run.call_args_list] == [
        "RETURN 1",
        "RETURN 1.5",
        "RETURN 2",
    ]
    assert session.run.return_value.consume.call_count == 3


def test_apply_neo4j_schema_refuses_an_empty_directory(tmp_path: Path):
    with pytest.raises(FileNotFoundError, match="No Neo4j schema files"):
        apply_neo4j_schema(MagicMock(), database="neo4j", schema_directory=tmp_path)


def test_checked_in_schema_owns_every_retrieval_index():
    schema = (NEO4J_SCHEMA_DIRECTORY / "001_retrieval_indexes.cypher").read_text()

    assert schema.count("CREATE FULLTEXT INDEX") == 3
    assert schema.count("CREATE RANGE INDEX") == 10
    assert schema.count("CREATE VECTOR INDEX") == 1
    assert "`vector.dimensions`: 768" in schema
    assert tuple(cypher_statements(schema))[-1] == "CALL db.awaitIndexes(30)"
