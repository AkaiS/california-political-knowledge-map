"""Contracts that keep every project-owned Pydantic AI agent observable."""

import ast
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from knowledge_map.utils import agents, telemetry


def test_telemetry_configures_before_instrumenting_pydantic_ai(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(telemetry, "_configured", False)
    monkeypatch.setattr(
        telemetry.logfire,
        "configure",
        lambda **kwargs: calls.append("configure"),
    )
    monkeypatch.setattr(
        telemetry.logfire,
        "instrument_pydantic_ai",
        lambda: calls.append("pydantic_ai"),
    )
    monkeypatch.setattr(
        telemetry.logfire,
        "instrument_httpx",
        lambda **kwargs: calls.append("httpx"),
    )
    monkeypatch.setattr(
        telemetry.logfire,
        "instrument_system_metrics",
        lambda: calls.append("system_metrics"),
    )

    telemetry.setup_telemetry()

    assert calls == ["configure", "pydantic_ai", "httpx", "system_metrics"]


def test_create_agent_sets_up_telemetry_before_construction(monkeypatch):
    calls: list[str] = []
    agent = MagicMock()
    monkeypatch.setattr(
        agents,
        "setup_telemetry",
        lambda: calls.append("telemetry"),
    )

    def construct(*args, **kwargs):
        calls.append("agent")
        return agent

    monkeypatch.setattr(agents, "Agent", construct)

    result = agents.create_agent("test:model", name="test_agent")

    assert result is agent
    assert calls == ["telemetry", "agent"]


def test_project_agents_use_the_observable_construction_seam_and_have_names():
    source_root = Path(__file__).parents[1] / "src"
    direct_agent_calls: list[str] = []
    unnamed_agent_calls: list[str] = []

    for path in source_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            if node.func.id == "Agent" and path.name != "agents.py":
                direct_agent_calls.append(f"{path}:{node.lineno}")
            if node.func.id == "create_agent" and not any(
                keyword.arg == "name" for keyword in node.keywords
            ):
                unnamed_agent_calls.append(f"{path}:{node.lineno}")

    assert direct_agent_calls == []
    assert unnamed_agent_calls == []


def test_missing_token_blocks_the_run(monkeypatch):
    """An unobservable run must fail at its start, not run and teach nothing."""
    monkeypatch.setattr(telemetry, "_configured", False)
    monkeypatch.setattr(telemetry, "_is_testing", lambda: False)
    monkeypatch.setattr(telemetry, "resolve_token", lambda: None)
    monkeypatch.delenv(telemetry.ALLOW_UNTRACED, raising=False)
    configured: list[str] = []
    monkeypatch.setattr(
        telemetry.logfire, "configure", lambda **kwargs: configured.append("configure")
    )

    with pytest.raises(telemetry.TelemetryNotConfiguredError) as error:
        telemetry.setup_telemetry()

    assert "keyring set logfire dev-telemetry" in str(error.value)
    assert configured == []


def test_allow_untraced_is_the_only_way_past_a_missing_token(monkeypatch):
    monkeypatch.setattr(telemetry, "_configured", False)
    monkeypatch.setattr(telemetry, "_is_testing", lambda: False)
    monkeypatch.setattr(telemetry, "resolve_token", lambda: None)
    monkeypatch.setenv(telemetry.ALLOW_UNTRACED, "1")
    for name in ("configure", "instrument_pydantic_ai", "instrument_httpx",
                 "instrument_system_metrics"):
        monkeypatch.setattr(telemetry.logfire, name, lambda *a, **k: None)

    telemetry.setup_telemetry()

    assert telemetry._configured is True


def test_token_prefers_environment_then_keychain_then_credentials_file(monkeypatch):
    monkeypatch.setattr(telemetry, "_credentials", lambda *a, **k: {"token": "file"})
    monkeypatch.setattr(telemetry, "_keychain_token", lambda: "keychain")
    monkeypatch.setenv(telemetry.LOGFIRE_TOKEN_ENV, "environment")
    assert telemetry.resolve_token() == "environment"

    monkeypatch.delenv(telemetry.LOGFIRE_TOKEN_ENV)
    assert telemetry.resolve_token() == "keychain"

    monkeypatch.setattr(telemetry, "_keychain_token", lambda: None)
    assert telemetry.resolve_token() == "file"


def test_resolved_token_is_passed_to_configure(monkeypatch):
    """The token must not depend on the directory the command was run from."""
    monkeypatch.setattr(telemetry, "_configured", False)
    monkeypatch.setattr(telemetry, "_is_testing", lambda: False)
    monkeypatch.setattr(telemetry, "resolve_token", lambda: "from-the-keychain")
    seen: dict[str, object] = {}
    monkeypatch.setattr(telemetry.logfire, "configure", lambda **kwargs: seen.update(kwargs))
    for name in ("instrument_pydantic_ai", "instrument_httpx", "instrument_system_metrics"):
        monkeypatch.setattr(telemetry.logfire, name, lambda *a, **k: None)

    telemetry.setup_telemetry()

    assert seen["token"] == "from-the-keychain"
