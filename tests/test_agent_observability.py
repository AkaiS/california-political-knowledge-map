"""Contracts that keep every project-owned Pydantic AI agent observable."""

import ast
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from knowledge_map.utils import agents, telemetry


def test_telemetry_configures_before_instrumenting_pydantic_ai(monkeypatch):
    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(telemetry, "_configured", False)
    monkeypatch.setenv("LOGFIRE_HTTPX_CAPTURE_ALL", "true")
    monkeypatch.setattr(
        telemetry.logfire,
        "configure",
        lambda **kwargs: calls.append(("configure", kwargs)),
    )
    monkeypatch.setattr(
        telemetry.logfire,
        "instrument_pydantic_ai",
        lambda **kwargs: calls.append(("pydantic_ai", kwargs)),
    )
    monkeypatch.setattr(
        telemetry.logfire,
        "instrument_httpx",
        lambda **kwargs: calls.append(("httpx", kwargs)),
    )
    monkeypatch.setattr(
        telemetry.logfire,
        "instrument_system_metrics",
        lambda: calls.append(("system_metrics", {})),
    )

    telemetry.setup_telemetry()

    assert [name for name, _ in calls] == [
        "configure",
        "pydantic_ai",
        "httpx",
        "system_metrics",
    ]
    assert dict(calls)["httpx"] == {"capture_all": False}
    assert dict(calls)["pydantic_ai"] == {"include_content": False}


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
    monkeypatch.setattr(telemetry, "_credential", None)
    monkeypatch.setattr(telemetry, "resolve_credential", lambda: None)
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
    monkeypatch.setattr(telemetry, "_credential", None)
    monkeypatch.setattr(telemetry, "resolve_credential", lambda: None)
    monkeypatch.setenv(telemetry.ALLOW_UNTRACED, "1")
    for name in (
        "configure",
        "instrument_pydantic_ai",
        "instrument_httpx",
        "instrument_system_metrics",
    ):
        monkeypatch.setattr(telemetry.logfire, name, lambda *a, **k: None)

    telemetry.setup_telemetry()

    assert telemetry._configured is True


def test_token_prefers_environment_then_keychain_then_credentials_file(monkeypatch):
    monkeypatch.setattr(telemetry, "_credential", None)
    monkeypatch.setattr(telemetry, "_verified_project_url", lambda: None)
    monkeypatch.delenv(telemetry.PROJECT_URL_ENV, raising=False)
    monkeypatch.setattr(telemetry, "_credentials", lambda *a, **k: {"token": "file"})
    monkeypatch.setattr(telemetry, "_keychain_token", lambda: "keychain")
    monkeypatch.setenv(telemetry.LOGFIRE_TOKEN_ENV, "environment")
    assert telemetry.resolve_token() == "environment"

    monkeypatch.delenv(telemetry.LOGFIRE_TOKEN_ENV)
    assert telemetry.resolve_token() == "keychain"

    monkeypatch.setattr(telemetry, "_keychain_token", lambda: None)
    assert telemetry.resolve_token() == "file"


def test_a_project_is_never_borrowed_from_a_source_that_did_not_supply_the_token(
    monkeypatch,
):
    """A stale credentials file must not name the project for another token.

    Pairing them would advertise a trace under a project it was never sent to,
    so an unverifiable pairing yields no project at all.
    """
    monkeypatch.setattr(telemetry, "_credential", None)
    monkeypatch.setattr(telemetry, "_verified_project_url", lambda: None)
    monkeypatch.delenv(telemetry.PROJECT_URL_ENV, raising=False)
    monkeypatch.delenv(telemetry.LOGFIRE_TOKEN_ENV, raising=False)
    monkeypatch.setattr(
        telemetry,
        "_credentials",
        lambda *a, **k: {"token": "file", "project_url": "https://logfire/other"},
    )
    monkeypatch.setattr(telemetry, "_keychain_token", lambda: "keychain")

    credential = telemetry.resolve_credential()

    assert credential.token == "keychain"
    assert credential.project_url is None


def test_the_credentials_file_names_the_project_for_its_own_token(monkeypatch):
    monkeypatch.setattr(telemetry, "_credential", None)
    monkeypatch.setattr(telemetry, "_verified_project_url", lambda: None)
    monkeypatch.delenv(telemetry.PROJECT_URL_ENV, raising=False)
    monkeypatch.delenv(telemetry.LOGFIRE_TOKEN_ENV, raising=False)
    monkeypatch.setattr(telemetry, "_keychain_token", lambda: None)
    monkeypatch.setattr(
        telemetry,
        "_credentials",
        lambda *a, **k: {"token": "file", "project_url": "https://logfire/mine"},
    )

    assert telemetry.project_url() == "https://logfire/mine"


def test_an_out_of_band_token_takes_its_project_from_the_declared_one(monkeypatch):
    monkeypatch.setattr(telemetry, "_credential", None)
    monkeypatch.setattr(telemetry, "_verified_project_url", lambda: None)
    monkeypatch.setenv(telemetry.LOGFIRE_TOKEN_ENV, "environment")
    monkeypatch.setenv(telemetry.PROJECT_URL_ENV, "https://logfire/declared")
    monkeypatch.setattr(
        telemetry,
        "_credentials",
        lambda *a, **k: {"token": "file", "project_url": "https://logfire/other"},
    )

    assert telemetry.project_url() == "https://logfire/declared"


def test_resolved_token_is_passed_to_configure(monkeypatch):
    """The token must not depend on the directory the command was run from."""
    monkeypatch.setattr(telemetry, "_configured", False)
    monkeypatch.setattr(telemetry, "_is_testing", lambda: False)
    monkeypatch.setattr(telemetry, "_credential", None)
    monkeypatch.setattr(
        telemetry,
        "resolve_credential",
        lambda: telemetry.LogfireCredential("from-the-keychain", None, "keychain"),
    )
    seen: dict[str, object] = {}
    monkeypatch.setattr(
        telemetry.logfire, "configure", lambda **kwargs: seen.update(kwargs)
    )
    for name in (
        "instrument_pydantic_ai",
        "instrument_httpx",
        "instrument_system_metrics",
    ):
        monkeypatch.setattr(telemetry.logfire, name, lambda *a, **k: None)

    telemetry.setup_telemetry()

    assert seen["token"] == "from-the-keychain"


def test_the_configured_project_survives_a_source_changing_mid_run(monkeypatch):
    """A report is written long after the run began, and sources are mutable.

    Re-reading them at report time could name a project this process never
    reported to, so the credential configure() was given is the one that answers.
    """
    monkeypatch.setattr(telemetry, "_configured", False)
    monkeypatch.setattr(telemetry, "_credential", None)
    monkeypatch.setattr(telemetry, "_is_testing", lambda: False)
    monkeypatch.setattr(telemetry, "_verified_project_url", lambda: None)
    monkeypatch.setattr(
        telemetry,
        "resolve_credential",
        lambda: telemetry.LogfireCredential(
            "token-at-startup", "https://logfire/reported-to", "keychain"
        ),
    )
    for name in (
        "configure",
        "instrument_pydantic_ai",
        "instrument_httpx",
        "instrument_system_metrics",
    ):
        monkeypatch.setattr(telemetry.logfire, name, lambda *a, **k: None)

    telemetry.setup_telemetry()

    # The sources move on: a rotated token, a credentials file for elsewhere.
    monkeypatch.setattr(
        telemetry,
        "resolve_credential",
        lambda: telemetry.LogfireCredential(
            "token-rotated", "https://logfire/somewhere-else", "file"
        ),
    )

    assert telemetry.project_url() == "https://logfire/reported-to"


def test_the_token_own_project_settles_a_declared_one_that_disagrees(monkeypatch):
    """LOGFIRE_PROJECT_URL is asserted by the operator, never checked.

    Logfire validates the token against the API and learns the project it
    actually belongs to, so that answer wins over a declaration naming another.
    """
    monkeypatch.setenv(telemetry.LOGFIRE_TOKEN_ENV, "environment")
    monkeypatch.setenv(telemetry.PROJECT_URL_ENV, "https://logfire/declared-wrong")
    monkeypatch.setattr(telemetry, "_credential", None)
    monkeypatch.setattr(
        telemetry, "_verified_project_url", lambda: "https://logfire/the-real-one"
    )

    assert telemetry.project_url() == "https://logfire/the-real-one"


def test_a_logfire_that_stops_exposing_its_project_degrades_to_the_declaration():
    """Internal state, read defensively: no project beats a raised exception."""

    class Config:
        pass

    class Instance:
        config = Config()

    with patch.object(telemetry.logfire, "DEFAULT_LOGFIRE_INSTANCE", Instance()):
        assert telemetry._verified_project_url() is None
