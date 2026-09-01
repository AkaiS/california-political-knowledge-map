"""Contracts that keep every project-owned Pydantic AI agent observable."""

import ast
from pathlib import Path
from unittest.mock import MagicMock

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
