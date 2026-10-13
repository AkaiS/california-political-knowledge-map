"""Boot the prepared, owner-only Bottle deployment without touching local data."""

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
import time
from contextlib import closing
from pathlib import Path
from urllib.parse import urlsplit

import httpx

REQUIRED_SECRETS = (
    "OPENROUTER_API_KEY",
    "TYPESAFE_API_KEY",
    "LOGFIRE_TOKEN",
    "NEO4J_PASSWORD",
    "OPENROUTER_MODEL",
    "OPENROUTER_PROVIDERS",
    "LOGFIRE_PROJECT_URL",
    "CLOUD_PUBLIC_ORIGIN",
)
BOTTLE_SECRET_NAMES = {
    "OPENROUTER_API_KEY": "OPENROUTER_KEY",
    "LOGFIRE_TOKEN": "LOGFIRE_API_KEY",
    "LOGFIRE_PROJECT_URL": "LOGFIRE_URL",
}
REQUIRED_BOTTLE_KEYS = tuple(
    BOTTLE_SECRET_NAMES.get(key, key) for key in REQUIRED_SECRETS
)
ARTIFACTS = ("neo4j.dump", "document_store.db", "embeddinggemma-300M-Q8_0.gguf")
OPTIONAL_CONFIGURATION = ("CLOUD_TRUSTED_PROXIES",)
EMBEDDING_SHA256 = "b5ce9d77a3fc4b3b39ccb5643c36777911cc4eb46a66962eadfa3f5f60490d63"


class CloudConfigurationError(RuntimeError):
    pass


def configure_cloud_transport() -> None:
    """Keep deployment transport waits within the question execution deadline."""
    for key, value in {
        "LLM_TRANSPORT_REQUEST_TIMEOUT": "60",
        "LLM_TRANSPORT_MAX_ATTEMPTS": "2",
        "LLM_TRANSPORT_RATE_LIMIT_WAIT_CAP": "15",
    }.items():
        os.environ.setdefault(key, value)


def load_secrets(*, client: httpx.Client | None = None) -> None:
    """Use the version 0.1.0 secrets response, failing before any agents exist."""
    mode = os.environ.get("CLOUD_SECRET_SOURCE", "bottle")
    if mode == "environment":
        values = {key: os.environ.get(key) for key in REQUIRED_SECRETS}
    elif mode == "bottle":
        router = os.environ.get("BOTTLE_ROUTER_URL", "")
        token = os.environ.get("BOTTLE_APP_TOKEN", "")
        if urlsplit(router).scheme not in {"http", "https"} or not token:
            raise CloudConfigurationError("Bottle router credentials are required")
        owns_client = client is None
        client = client or httpx.Client(timeout=15, follow_redirects=False)
        try:
            response = client.post(
                router.rstrip("/") + "/api/services/v2/call/secrets/get",
                headers={"Authorization": f"Bearer {token}"},
                json={"keys": list(REQUIRED_BOTTLE_KEYS + OPTIONAL_CONFIGURATION)},
            )
            response.raise_for_status()
            body = response.json()
            received = body.get("secrets") if isinstance(body, dict) else None
            if not isinstance(received, dict) or set(body.get("missing", [])) & set(
                REQUIRED_BOTTLE_KEYS
            ):
                raise CloudConfigurationError("Required Bottle secrets are unavailable")
            values = {
                key: received.get(BOTTLE_SECRET_NAMES.get(key, key))
                for key in REQUIRED_SECRETS
            }
            values.update({key: received.get(key) for key in OPTIONAL_CONFIGURATION})
        except (httpx.HTTPError, ValueError):
            # Service responses can contain secret values and must never be logged.
            raise CloudConfigurationError("Bottle secrets service failed") from None
        finally:
            if owns_client:
                client.close()
    else:
        raise CloudConfigurationError("Unknown CLOUD_SECRET_SOURCE")
    if any(
        not isinstance(values.get(key), str) or not values[key].strip()
        for key in REQUIRED_SECRETS
    ):
        raise CloudConfigurationError("All deployment secrets must be present")
    password = values["NEO4J_PASSWORD"]
    if (
        len(password) < 16
        or password.lower() in {"passwordpassword", "neo4jneo4jneo4jneo4j"}
        or any(c in password for c in "\r\n\0")
    ):
        raise CloudConfigurationError(
            "Use a fresh Neo4j password of at least 16 characters"
        )
    os.environ.update({key: values[key] for key in REQUIRED_SECRETS})
    for key in OPTIONAL_CONFIGURATION:
        value = values.get(key)
        if value is not None:
            if not isinstance(value, str):
                raise CloudConfigurationError(
                    "Optional deployment configuration must be text"
                )
            os.environ[key] = value
    origin = urlsplit(values["CLOUD_PUBLIC_ORIGIN"])
    if (
        origin.scheme != "https"
        or not origin.hostname
        or origin.path
        or origin.query
        or origin.fragment
        or origin.username
        or origin.password
    ):
        raise CloudConfigurationError(
            "CLOUD_PUBLIC_ORIGIN must be an explicit HTTPS origin"
        )


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def validate_sqlite(path: Path, *, sanitized: bool) -> None:
    with closing(sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)) as connection:
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise CloudConfigurationError("SQLite corpus failed integrity check")
        required_columns = {
            "stories": {"id", "url", "content"},
            "publications": {"id", "name"},
            "scraped_html_cache": {"url", "publication_id"},
            "story_links": {"id", "story_id", "text", "url", "scraped", "created_at"},
        }
        for table, columns in required_columns.items():
            actual = {
                row[1] for row in connection.execute(f"PRAGMA table_info({table})")
            }
            if not columns <= actual:
                raise CloudConfigurationError(
                    f"SQLite reader schema is incompatible: {table}"
                )
        for table in ("stories", "publications"):
            if connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0:
                raise CloudConfigurationError("SQLite corpus is empty")
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        optional_columns = {
            "source_guides": {
                "guide_id",
                "question",
                "created_at",
                "latest_attempt_id",
                "content_json",
                "retrieved_at",
            },
            "source_guide_attempts": {
                "attempt_id",
                "guide_id",
                "started_at",
                "finished_at",
                "status",
                "outcome_json",
            },
            "public_daily_admissions": {"day", "submissions"},
        }
        identity_columns = {
            "source_guides": "guide_id",
            "source_guide_attempts": "attempt_id",
            "public_daily_admissions": "day",
        }
        for table, columns in optional_columns.items():
            if table in tables:
                info = list(connection.execute(f"PRAGMA table_info({table})"))
                actual = {row[1] for row in info}
                primary_keys = {row[1] for row in info if row[5]}
                if not columns <= actual or primary_keys != {identity_columns[table]}:
                    raise CloudConfigurationError(
                        f"SQLite guide schema is incompatible: {table}"
                    )
        if sanitized:
            for table in tables & {
                "source_guides",
                "source_guide_attempts",
                "public_daily_admissions",
                "public_rate_limits",
            }:
                if connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]:
                    raise CloudConfigurationError(
                        "Seed SQLite contains private guide or admission state"
                    )


def configure_paths(root: Path) -> None:
    """Set persistence before importing application settings or database adapters."""
    configure_cloud_transport()
    if not root.is_absolute():
        raise CloudConfigurationError("BOTTLE_APP_DATA_DIR must be absolute")
    for relative in ("neo4j", "sqlite", "models", "recovery"):
        (root / relative).mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryFile(dir=root):
        pass
    os.environ.update(
        SQLITE_DB_PATH=str(root / "sqlite/document_store.db"),
        EMBED_GGUF=str(root / "models/embeddinggemma-300M-Q8_0.gguf"),
        NEO4J_URI="bolt://127.0.0.1:7687",
        NEO4J_USERNAME="neo4j",
        NEO4J_DATABASE="neo4j",
        LLAMA_CPP_EMBEDDING_BASE_URL="http://127.0.0.1:8081",
        EMBEDDING_MODEL="embeddinggemma",
        CHAT_DEPLOYMENT="openrouter",
        DEPLOYMENT_ENVIRONMENT="production",
        CLOUD_PUBLIC_MODE="1",
        CLOUD_FRAME_ANCESTORS="https://akaisenghor.com https://www.akaisenghor.com",
    )
    conf = Path(tempfile.mkdtemp(prefix="knowledge-map-neo4j-"))
    shutil.copytree(
        Path(os.environ.get("NEO4J_HOME", "/var/lib/neo4j")) / "conf",
        conf,
        dirs_exist_ok=True,
    )
    (conf / "neo4j.conf").write_text(
        f"server.directories.data={root / 'neo4j'}\n"
        f"server.directories.logs={root / 'neo4j/logs'}\n"
        "server.directories.run=/tmp/knowledge-map-neo4j-run\n"
        "server.default_listen_address=127.0.0.1\n"
        "server.bolt.listen_address=127.0.0.1:7687\n"
        "server.bolt.advertised_address=127.0.0.1:7687\n"
        "server.http.enabled=false\nserver.https.enabled=false\n"
        "server.memory.heap.initial_size=1G\nserver.memory.heap.max_size=1G\n"
        "server.memory.pagecache.size=1G\ndbms.security.auth_enabled=true\n"
        "dbms.logs.query.enabled=OFF\n",
        encoding="utf-8",
    )
    os.environ["NEO4J_CONF"] = str(conf)


def prepare_data(root: Path) -> None:
    """Restore one immutable corpus; refuse partial restores and replacements."""
    marker = root / "recovery/installed-release.json"
    if marker.exists():
        installed = json.loads(marker.read_text())
        if installed["neo4j_version"] != os.environ["NEO4J_VERSION"]:
            raise CloudConfigurationError(
                "Neo4j release differs from the installed corpus"
            )
        if not (root / "neo4j/databases/neo4j").is_dir():
            raise CloudConfigurationError("Installed graph is missing")
        validate_sqlite(root / "sqlite/document_store.db", sanitized=False)
        if sha256(root / "models" / ARTIFACTS[2]) != EMBEDDING_SHA256:
            raise CloudConfigurationError(
                "Installed embedding artifact checksum differs"
            )
        return
    if any(
        (root / relative).exists()
        for relative in (
            "neo4j/databases",
            "sqlite/document_store.db",
            "models/" + ARTIFACTS[2],
        )
    ):
        raise CloudConfigurationError(
            "Unmarked existing data needs operator recovery; refusing overwrite"
        )
    seed = root / "recovery/seed"
    release = json.loads((seed / "release.json").read_text())
    if release.get("neo4j_version") != os.environ["NEO4J_VERSION"] or not release.get(
        "corpus_id"
    ):
        raise CloudConfigurationError("Seed must identify a compatible corpus release")
    for name in ARTIFACTS:
        digest = release.get("sha256", {}).get(name, "")
        if not re.fullmatch(r"[0-9a-f]{64}", digest) or sha256(seed / name) != digest:
            raise CloudConfigurationError(f"Seed checksum differs: {name}")
    if release["sha256"][ARTIFACTS[2]] != EMBEDDING_SHA256:
        raise CloudConfigurationError(
            "Seed must use the frozen EmbeddingGemma artifact"
        )
    validate_sqlite(seed / "document_store.db", sanitized=True)
    admin = str(
        Path(os.environ.get("NEO4J_HOME", "/var/lib/neo4j")) / "bin/neo4j-admin"
    )
    subprocess.run(
        [
            admin,
            "database",
            "load",
            "neo4j",
            f"--from-path={seed}",
            "--overwrite-destination=false",
        ],
        check=True,
    )
    # Picocli argument files keep the fresh password out of process arguments.
    with tempfile.NamedTemporaryFile(
        mode="w", prefix="knowledge-map-password-"
    ) as secret:
        secret.write(json.dumps(os.environ["NEO4J_PASSWORD"]) + "\n")
        secret.flush()
        subprocess.run(
            [admin, "dbms", "set-initial-password", "@" + secret.name],
            check=True,
            stdout=subprocess.DEVNULL,
        )
    shutil.copyfile(seed / "document_store.db", root / "sqlite/document_store.db")
    shutil.copyfile(seed / ARTIFACTS[2], root / "models" / ARTIFACTS[2])
    marker.write_text(json.dumps(release, indent=2) + "\n")


def dependencies_ready() -> bool:
    """Check authenticated graph access and embedding health without inference."""
    from neo4j import GraphDatabase
    from neo4j.exceptions import DriverError, Neo4jError

    try:
        with httpx.Client(timeout=2, trust_env=False) as client:
            if client.get("http://127.0.0.1:8081/health").status_code != 200:
                return False
        with GraphDatabase.driver(
            os.environ["NEO4J_URI"],
            auth=("neo4j", os.environ["NEO4J_PASSWORD"]),
            connection_timeout=2,
            connection_acquisition_timeout=2,
            max_transaction_retry_time=0,
        ) as driver:
            driver.verify_connectivity()
        return True
    except (httpx.HTTPError, Neo4jError, DriverError, OSError):
        return False


def run_web() -> None:
    configure_cloud_transport()
    deadline = time.monotonic() + 180
    while not dependencies_ready():
        if time.monotonic() >= deadline:
            raise CloudConfigurationError("Required services did not become ready")
        time.sleep(1)
    from knowledge_map.utils.telemetry import setup_telemetry

    setup_telemetry()
    # Agent construction imports follow telemetry initialization.
    import uvicorn

    from knowledge_map.public_access import PublicSettings
    from knowledge_map.web import create_app

    app = create_app(
        public_settings=PublicSettings.from_environment(), readiness=dependencies_ready
    )
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8080,
        workers=1,
        proxy_headers=False,
        timeout_graceful_shutdown=45,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("bootstrap", "web"))
    args = parser.parse_args()
    if args.command == "web":
        run_web()
        return
    load_secrets()
    for name in ("OPENROUTER_MODEL", "OPENROUTER_PROVIDERS", "LOGFIRE_PROJECT_URL"):
        if not os.environ.get(name):
            raise CloudConfigurationError(f"{name} must be selected explicitly")
    if not os.environ.get("BOTTLE_APP_DATA_DIR"):
        raise CloudConfigurationError("BOTTLE_APP_DATA_DIR is required")
    root = Path(os.environ["BOTTLE_APP_DATA_DIR"])
    configure_paths(root)
    prepare_data(root)
    os.execv(
        "/app/.venv/bin/supervisord",
        ["supervisord", "-c", "/app/deployment/supervisord.conf"],
    )


if __name__ == "__main__":
    try:
        main()
    except CloudConfigurationError as error:
        raise SystemExit(str(error)) from None
