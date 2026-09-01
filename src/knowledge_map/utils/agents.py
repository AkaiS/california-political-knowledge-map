"""The required construction seam for observable Pydantic AI agents."""

from typing import Any

from pydantic_ai import Agent

from knowledge_map.utils.telemetry import setup_telemetry


def create_agent(*args: Any, **kwargs: Any) -> Agent:
    """Configure Logfire before constructing a Pydantic AI agent."""

    setup_telemetry()
    return Agent(*args, **kwargs)
