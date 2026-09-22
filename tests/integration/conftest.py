"""Opt-in integration tests own an isolated Neo4j container, never a user graph."""

import os
import subprocess
import time
from collections.abc import Iterator

import pytest
from neo4j import GraphDatabase
from neo4j.exceptions import ServiceUnavailable

from knowledge_map.database_setup import apply_neo4j_schema


@pytest.fixture(scope="session")
def disposable_neo4j_uri() -> Iterator[str]:
    if os.environ.get("RUN_NEO4J_INTEGRATION") != "1":
        pytest.skip("set RUN_NEO4J_INTEGRATION=1 to start disposable Neo4j")
    container = subprocess.check_output(
        [
            "docker",
            "run",
            "--detach",
            "--rm",
            "--publish",
            "127.0.0.1::7687",
            "--env",
            "NEO4J_AUTH=none",
            "--env",
            "NEO4J_server_memory_heap_initial__size=128m",
            "--env",
            "NEO4J_server_memory_heap_max__size=256m",
            "--env",
            "NEO4J_server_memory_pagecache_size=128m",
            "neo4j:2026.07.1",
        ],
        text=True,
    ).strip()
    try:
        address = subprocess.check_output(
            ["docker", "port", container, "7687/tcp"], text=True
        ).strip()
        uri = f"bolt://{address}"
        until = time.monotonic() + 60
        with GraphDatabase.driver(uri) as driver:
            while True:
                try:
                    driver.verify_connectivity()
                    break
                except ServiceUnavailable:
                    if time.monotonic() >= until:
                        pytest.fail("disposable Neo4j did not become ready")
                    time.sleep(0.25)
        yield uri
    finally:
        subprocess.run(["docker", "stop", container], check=True, capture_output=True)


@pytest.fixture
def neo4j_schema_uri(disposable_neo4j_uri: str) -> str:
    """Apply the production Neo4j schema to the disposable database."""

    with GraphDatabase.driver(disposable_neo4j_uri) as driver:
        apply_neo4j_schema(driver, database="neo4j")
    return disposable_neo4j_uri
