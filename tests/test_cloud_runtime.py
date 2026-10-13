import hashlib
import json
import sqlite3
import subprocess
import tomllib
from pathlib import Path

import httpx
import pytest
from packaging.specifiers import SpecifierSet

from knowledge_map.cloud_runtime import (
    ARTIFACTS,
    BOTTLE_SECRET_NAMES,
    OPTIONAL_CONFIGURATION,
    REQUIRED_BOTTLE_KEYS,
    REQUIRED_SECRETS,
    CloudConfigurationError,
    configure_cloud_transport,
    load_secrets,
    prepare_data,
    validate_sqlite,
)


def secrets():
    return {
        **{key: "DedicatedDeploymentSecret123!" for key in REQUIRED_SECRETS},
        "CLOUD_PUBLIC_ORIGIN": "https://guides.example",
    }


def test_manifest_consumes_exact_compatible_secrets_service():
    root = Path(__file__).resolve().parents[1]
    manifest = tomllib.loads((root / "cloudinabottle.toml").read_text())
    service = manifest["services"]["v2"]["consumes"][0]
    constraint = SpecifierSet(service["version"])
    assert "0.1.0" in constraint
    assert "0.1.1" not in constraint
    assert "0.2.0" not in constraint
    assert [grant["key"] for grant in service["grants"]] == list(
        REQUIRED_BOTTLE_KEYS + OPTIONAL_CONFIGURATION
    )
    assert manifest["routing"]["public_paths"] == []


def bottle_secrets():
    return {
        BOTTLE_SECRET_NAMES.get(key, key): value for key, value in secrets().items()
    }


def test_bottle_granted_secrets_contract(monkeypatch):
    monkeypatch.setenv("BOTTLE_ROUTER_URL", "https://bottle.example")
    monkeypatch.setenv("BOTTLE_APP_TOKEN", "app-token")
    monkeypatch.delenv("CLOUD_SECRET_SOURCE", raising=False)

    def service(request):
        assert request.url.path == "/api/services/v2/call/secrets/get"
        assert request.headers["Authorization"] == "Bearer app-token"
        assert json.loads(request.content) == {
            "keys": list(REQUIRED_BOTTLE_KEYS + OPTIONAL_CONFIGURATION)
        }
        return httpx.Response(200, json={"secrets": bottle_secrets(), "missing": []})

    with httpx.Client(transport=httpx.MockTransport(service)) as client:
        load_secrets(client=client)
    for key in REQUIRED_SECRETS:
        assert __import__("os").environ[key] == secrets()[key]


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"secrets": {}},
        {"secrets": bottle_secrets(), "missing": ["LOGFIRE_API_KEY"]},
        {"secrets": {**bottle_secrets(), "NEO4J_PASSWORD": "neo4j"}},
        {"secrets": secrets(), "missing": []},
    ],
)
def test_incomplete_secrets_refuse_startup(monkeypatch, body):
    monkeypatch.setenv("BOTTLE_ROUTER_URL", "https://bottle.example")
    monkeypatch.setenv("BOTTLE_APP_TOKEN", "app-token")
    monkeypatch.setenv("CLOUD_SECRET_SOURCE", "bottle")
    with (
        httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json=body)
            )
        ) as client,
        pytest.raises(CloudConfigurationError),
    ):
        load_secrets(client=client)


@pytest.mark.parametrize(
    "missing_alias", ["OPENROUTER_KEY", "LOGFIRE_API_KEY", "LOGFIRE_URL"]
)
def test_missing_bottle_alias_does_not_fall_back_to_environment(
    monkeypatch, missing_alias
):
    monkeypatch.setenv("CLOUD_SECRET_SOURCE", "bottle")
    monkeypatch.setenv("BOTTLE_ROUTER_URL", "https://bottle.example")
    monkeypatch.setenv("BOTTLE_APP_TOKEN", "app-token")
    for key, value in secrets().items():
        monkeypatch.setenv(key, value)
    supplied = bottle_secrets()
    del supplied[missing_alias]
    with (
        httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json={"secrets": supplied})
            )
        ) as client,
        pytest.raises(CloudConfigurationError),
    ):
        load_secrets(client=client)


def test_direct_environment_mode_uses_only_canonical_names(monkeypatch):
    monkeypatch.setenv("CLOUD_SECRET_SOURCE", "environment")
    for key, value in secrets().items():
        monkeypatch.setenv(key, value)
    for alias in BOTTLE_SECRET_NAMES.values():
        monkeypatch.delenv(alias, raising=False)
    load_secrets()
    assert __import__("os").environ["LOGFIRE_TOKEN"] == secrets()["LOGFIRE_TOKEN"]


def test_environment_mode_does_not_accept_bottle_aliases(monkeypatch):
    monkeypatch.setenv("CLOUD_SECRET_SOURCE", "environment")
    for key, value in secrets().items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("OPENROUTER_API_KEY")
    monkeypatch.setenv("OPENROUTER_KEY", "alias-value")
    with pytest.raises(CloudConfigurationError):
        load_secrets()


def make_seed(root: Path, *, private: bool = False):
    seed = root / "recovery/seed"
    seed.mkdir(parents=True)
    db = seed / "document_store.db"
    with sqlite3.connect(db) as connection:
        connection.executescript(
            "CREATE TABLE stories(id,url,content); INSERT INTO stories VALUES(1,'url','content'); CREATE TABLE publications(id,name); INSERT INTO publications VALUES(1,'publication'); CREATE TABLE scraped_html_cache(url,publication_id); CREATE TABLE story_links(id,story_id,text,url,scraped,created_at); CREATE TABLE source_guides(guide_id TEXT PRIMARY KEY,question,created_at,latest_attempt_id,content_json,retrieved_at);"
        )
        if private:
            connection.execute(
                "INSERT INTO source_guides(question) VALUES('private question')"
            )
    (seed / "neo4j.dump").write_bytes(b"graph fixture")
    (seed / ARTIFACTS[2]).write_bytes(b"model fixture")
    release = {
        "corpus_id": "fixture",
        "neo4j_version": "2026.07.1",
        "sha256": {
            name: hashlib.sha256((seed / name).read_bytes()).hexdigest()
            for name in ARTIFACTS
        },
    }
    (seed / "release.json").write_text(json.dumps(release))
    (root / "models").mkdir()
    (root / "sqlite").mkdir()
    return seed


def test_private_seed_rejected_without_touching_original(tmp_path):
    seed = make_seed(tmp_path, private=True)
    before = (seed / "document_store.db").read_bytes()
    with pytest.raises(CloudConfigurationError, match="private"):
        validate_sqlite(seed / "document_store.db", sanitized=True)
    assert (seed / "document_store.db").read_bytes() == before


def test_restore_checksums_before_loading_graph(tmp_path, monkeypatch):
    seed = make_seed(tmp_path)
    monkeypatch.setenv("NEO4J_VERSION", "2026.07.1")
    (seed / ARTIFACTS[2]).write_bytes(b"different conversion")
    with pytest.raises(CloudConfigurationError, match="checksum"):
        prepare_data(tmp_path)
    assert not (tmp_path / "sqlite/document_store.db").exists()


def test_partial_restore_never_overwrites_data(tmp_path, monkeypatch):
    make_seed(tmp_path)
    monkeypatch.setenv("NEO4J_VERSION", "2026.07.1")
    db = tmp_path / "sqlite/document_store.db"
    db.write_bytes(b"existing visitors")
    with pytest.raises(CloudConfigurationError, match="refusing overwrite"):
        prepare_data(tmp_path)
    assert db.read_bytes() == b"existing visitors"


def test_fresh_auth_uses_private_argument_file_and_cleans_it(tmp_path, monkeypatch):
    seed = make_seed(tmp_path)
    monkeypatch.setenv("NEO4J_VERSION", "2026.07.1")
    password = "FreshPasswordForDeployment123"
    monkeypatch.setenv("NEO4J_PASSWORD", password)
    monkeypatch.setattr(
        "knowledge_map.cloud_runtime.EMBEDDING_SHA256",
        hashlib.sha256((seed / ARTIFACTS[2]).read_bytes()).hexdigest(),
    )
    argument_files = []

    def admin(arguments, **kwargs):
        assert password not in " ".join(arguments)
        if arguments[1:3] == ["database", "load"]:
            (tmp_path / "neo4j/databases/neo4j").mkdir(parents=True)
        else:
            argument_file = Path(arguments[-1][1:])
            assert arguments[-1].startswith("@")
            assert argument_file.stat().st_mode & 0o777 == 0o600
            assert json.loads(argument_file.read_text()) == password
            argument_files.append(argument_file)

    monkeypatch.setattr("knowledge_map.cloud_runtime.subprocess.run", admin)
    prepare_data(tmp_path)
    assert (tmp_path / "recovery/installed-release.json").exists()
    assert argument_files and not argument_files[0].exists()


def test_cloud_transport_before_first_settings_import(monkeypatch):
    for name in (
        "LLM_TRANSPORT_REQUEST_TIMEOUT",
        "LLM_TRANSPORT_MAX_ATTEMPTS",
        "LLM_TRANSPORT_RATE_LIMIT_WAIT_CAP",
    ):
        monkeypatch.delenv(name, raising=False)
    script = """
import json
from knowledge_map.cloud_runtime import configure_cloud_transport
configure_cloud_transport()
from knowledge_map.config import settings, configured_model_request_settings
from knowledge_map.public_access import PublicSettings
request = configured_model_request_settings()
print(json.dumps({
    'embedding': settings.transport.model_dump(),
    'chat': [request.timeout, request.max_attempts, request.rate_limit_wait_cap],
    'deadline': PublicSettings().deadline_seconds,
}))
"""
    result = subprocess.run(
        ["uv", "run", "--no-sync", "python", "-c", script],
        capture_output=True,
        text=True,
        check=True,
    )
    configured = json.loads(result.stdout)
    assert configured["embedding"] == {
        "request_timeout": 60.0,
        "max_attempts": 2,
        "rate_limit_wait_cap": 15,
    }
    assert configured["chat"] == [60.0, 2, 15]
    assert configured["deadline"] == 240


def test_cloud_transport_preserves_explicit_settings(monkeypatch):
    monkeypatch.setenv("LLM_TRANSPORT_REQUEST_TIMEOUT", "30")
    configure_cloud_transport()
    from knowledge_map.config import TransportSettings

    assert TransportSettings().request_timeout == 30
