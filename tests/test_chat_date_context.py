"""Inspect date inputs at the real Chat Session model-request boundaries."""

import asyncio
import json
from datetime import UTC, datetime, timedelta

import pytest
from pydantic_ai.messages import ModelResponse, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import FunctionModel
from test_query_preparation import rewrite_response, rewriter_agent
from test_retrieval import COVERAGE, coordinator

from knowledge_map.core import chat


def test_session_date_survives_correction_and_guidance_across_midnight(monkeypatch):
    class Clock(datetime):
        current = datetime(2026, 10, 1, 23, 59, tzinfo=UTC)

        @classmethod
        def now(cls, tz=None):
            return cls.current

    monkeypatch.setattr(chat, "datetime", Clock)
    requests = []

    def respond(messages, info):
        requests.append(
            [
                part.content
                for message in messages
                for part in message.parts
                if isinstance(part, UserPromptPart)
            ]
        )
        output = (
            {"status": "allowed"}
            if len(requests) <= 2
            else {"introduction": "Read the available reporting."}
        )
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, output)])

    question = "Which unions supported AB 1 in September 2026?"
    agent, rewriter = chat.get_chat_agent(), rewriter_agent()
    session = chat.ChatSession(
        question,
        chat_agent=agent,
        rewriter=rewriter,
        retrieval=coordinator(),
        coverage=COVERAGE,
        relevant_collection_ids=("reporting",),
    )

    async def exercise():
        assert (await session.prepare()).status == "awaiting_approval"
        Clock.current += timedelta(minutes=2)
        session.reject("Keep the September 2026 period.")
        assert (await session.prepare()).status == "awaiting_approval"
        await session.approve()

    with (
        agent.override(model=FunctionModel(respond)),
        rewriter.override(model=rewrite_response(question, False)),
    ):
        asyncio.run(exercise())

    for prompts in requests:
        context = json.loads(prompts[0])
        assert context["current_date"] == "2026-10-01"
        assert context["as_of"] == "2026-10-01T23:59:00+00:00"
    assert session.as_of == datetime(2026, 10, 1, 23, 59, tzinfo=UTC)


def test_supplied_session_time_is_normalized_to_utc_and_requires_a_timezone():
    agent, rewriter = chat.get_chat_agent(), rewriter_agent()
    kwargs = {
        "chat_agent": agent,
        "rewriter": rewriter,
        "retrieval": coordinator(),
        "coverage": COVERAGE,
        "relevant_collection_ids": ("reporting",),
    }
    session = chat.ChatSession(
        "Who supported AB 1?",
        as_of=datetime.fromisoformat("2026-09-30T20:00:00-07:00"),
        **kwargs,
    )
    assert session.as_of == datetime(2026, 10, 1, 3, tzinfo=UTC)
    with pytest.raises(ValueError, match="timezone"):
        chat.ChatSession(
            "Who supported AB 1?",
            as_of=datetime(2026, 10, 1, tzinfo=UTC).replace(tzinfo=None),
            **kwargs,
        )
