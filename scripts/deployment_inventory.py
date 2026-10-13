"""Read-only release inventory. Credentials stay in memory and never enter reports."""

import argparse
import hashlib
import json
import logging
import os
import platform
import shutil
import sqlite3
import subprocess
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def readonly_sqlite(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)


def quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def sqlite_inventory(path: Path) -> dict:
    with closing(readonly_sqlite(path)) as connection:
        tables = connection.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        result = {
            "file_bytes": path.stat().st_size,
            "wal_bytes": Path(str(path) + "-wal").stat().st_size
            if Path(str(path) + "-wal").exists() else 0,
            "tables": {
                name: {
                    "rows": connection.execute(
                        f"SELECT count(*) FROM {quote_identifier(name)}"
                    ).fetchone()[0],
                    "schema": schema,
                }
                for name, schema in tables
            },
            "user_version": connection.execute("PRAGMA user_version").fetchone()[0],
            "integrity": connection.execute("PRAGMA quick_check").fetchone()[0],
        }
        if "publications" in result["tables"]:
            result["publications"] = [
                {"name": name, "base_url": url}
                for name, url in connection.execute("SELECT name, base_url FROM publications")
            ]
        if "stories" in result["tables"]:
            result["story_status_counts"] = dict(connection.execute(
                "SELECT status, count(*) FROM stories GROUP BY status"
            ))
        return result


def command_metadata(command: list[str], *, timeout: int = 15) -> dict:
    """Only use fixed metadata commands here, never environment or log commands."""
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
        if result.returncode:
            return {"available": False, "exit_code": result.returncode}
        return {"available": True, "output": result.stdout.strip() or result.stderr.strip()}
    except (OSError, subprocess.TimeoutExpired) as error:
        return {"available": False, "error_type": type(error).__name__}


def neo4j_inventory(sqlite_path: Path) -> dict:
    from neo4j import READ_ACCESS, GraphDatabase
    from neo4j.exceptions import DriverError, Neo4jError

    logging.getLogger("neo4j").setLevel(logging.CRITICAL)
    required = ("NEO4J_URI", "NEO4J_USERNAME", "NEO4J_PASSWORD")
    if not all(os.environ.get(name) for name in required):
        return {"available": False, "reason": "Neo4j connection configuration is incomplete"}
    try:
        with GraphDatabase.driver(
            os.environ["NEO4J_URI"],
            auth=(os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"]),
            connection_timeout=5,
            max_transaction_retry_time=0,
        ) as driver, driver.session(
            database=os.environ.get("NEO4J_DATABASE", "neo4j"),
            default_access_mode=READ_ACCESS,
        ) as session:
            queries = {
                "components": "CALL dbms.components() YIELD name, versions, edition RETURN name, versions, edition",
                "nodes": "MATCH (n) RETURN count(n) AS count",
                "relationships": "MATCH ()-[r]->() RETURN count(r) AS count",
                "labels": "MATCH (n) UNWIND labels(n) AS label RETURN label, count(*) AS count ORDER BY label",
                "relationship_types": "MATCH ()-[r]->() RETURN type(r) AS type, count(*) AS count ORDER BY type",
                "indexes": "SHOW INDEXES YIELD name,type,state,populationPercent,labelsOrTypes,properties,options RETURN name,type,state,populationPercent,labelsOrTypes,properties,options ORDER BY name",
            }
            result = {"available": True}
            for name, query in queries.items():
                result[name] = session.execute_read(lambda tx, q=query: tx.run(q).data())
            articles = session.execute_read(lambda tx: tx.run(
                "MATCH (n:NewsArticle) RETURN n.id AS id"
            ).data())
            with closing(readonly_sqlite(sqlite_path)) as connection:
                story_urls = {row[0] for row in connection.execute("SELECT url FROM stories")}
            result["corpus_alignment"] = {
                "graph_articles": len(articles),
                "graph_articles_with_sqlite_story": sum(a["id"] in story_urls for a in articles),
                "sqlite_stories": len(story_urls),
            }
            result["all_indexes_online"] = all(
                index["state"] == "ONLINE" for index in result["indexes"]
            )
            return result
    except (DriverError, Neo4jError, OSError, sqlite3.Error) as error:
        # Driver exception text may contain connection information; do not serialize it.
        return {"available": False, "error_type": type(error).__name__}


def docker_inventory(container: str | None) -> dict:
    result = {"version": command_metadata(["docker", "version", "--format", "{{json .}}"])}
    if container:
        image = command_metadata(["docker", "inspect", "--format", "{{.Config.Image}}", container])
        result.update({
            "container": container,
            "image": image,
            "java": command_metadata(["docker", "exec", container, "java", "-version"]),
            "data_kib": command_metadata(["docker", "exec", container, "du", "-sk", "/data/databases/neo4j", "/data/transactions/neo4j"]),
            "idle_memory": command_metadata(["docker", "stats", "--no-stream", "--format", "{{.MemUsage}}", container]),
            "mounts": command_metadata(["docker", "inspect", "--format", "{{json .Mounts}}", container]),
            "image_digest": command_metadata(["docker", "image", "inspect", image["output"], "--format", "{{json .RepoDigests}}"])
            if image.get("available") else {"available": False},
        })
    return result


def collect_inventory(sqlite_path: Path, gguf: Path, container: str | None) -> dict:
    binary = shutil.which("llama-server")
    result = {
        "format_version": 1,
        "recorded_at": datetime.now(UTC).isoformat(),
        "application_commit": command_metadata(["git", "rev-parse", "HEAD"]),
        "python": platform.python_version(),
        "uv": command_metadata(["uv", "--version"]),
        "local_system": {"os": platform.system(), "architecture": platform.machine()},
        "hosted_architecture": None,
        "sqlite": sqlite_inventory(sqlite_path),
        "neo4j": neo4j_inventory(sqlite_path),
        "docker": docker_inventory(container),
        "llama_cpp": {
            "version": command_metadata([binary, "--version"]) if binary else {"available": False},
            "binary_sha256": sha256_file(Path(binary).resolve()) if binary else None,
        },
        "embedding_artifact": {
            "filename": gguf.name,
            "available": gguf.is_file(),
            "bytes": gguf.stat().st_size if gguf.is_file() else None,
            "sha256": sha256_file(gguf) if gguf.is_file() else None,
            "dimensions": 768,
            "context": 2048,
            "batch_size": 2048,
            "ubatch_size": 2048,
            "pooling": "GGUF mean pooling; do not override",
            "projection": "Original ggml-org conversion with dense_2/dense_3 projection tensors",
            "linux_gpu_layers": 0,
        },
        "memory_measurement": {
            "scope": "Local idle only; Darwin processes and Docker Desktop VM differ from hosted Linux",
            "process_rss": command_metadata(["ps", "-axo", "pid,rss,comm"]),
            "linux_peak_question_bytes": None,
        },
        "release_gates": [
            "Hosted architecture not measured",
            "Offline graph dump and disposable restore pending; local Neo4j remains running",
            "Linux peak whole-question memory not measured",
            "Dedicated capped OpenRouter key and Jev billing not verified",
        ],
    }
    # Retain only service RSS, without arguments that might carry credentials.
    process_result = result["memory_measurement"]["process_rss"]
    if process_result.get("available"):
        process_result["output"] = "\n".join(
            line for line in process_result["output"].splitlines()
            if any(service in line.lower() for service in ("llama-server", "uvicorn", "python", "java"))
        )
    return result


def main() -> None:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sqlite", type=Path, default=Path(os.environ.get("SQLITE_DB_PATH", "document_store.db")))
    parser.add_argument("--gguf", type=Path, default=Path(os.environ.get("EMBED_GGUF", str(Path.home() / "Library/Caches/llama.cpp/embeddinggemma-300M-Q8_0.gguf"))))
    parser.add_argument("--neo4j-container", help="Existing container name or ID for read-only runtime metadata")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = collect_inventory(args.sqlite, args.gguf, args.neo4j_container)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(f"Inventory written to {args.output}")


if __name__ == "__main__":
    main()
