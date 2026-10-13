"""Gemma assessment at the real session and OpenRouter HTTP schema boundary."""

import asyncio
import json
from datetime import datetime
from typing import cast

import httpx
import pytest
from jsonschema import Draft202012Validator, FormatChecker
from pydantic_ai.exceptions import UnexpectedModelBehavior

from knowledge_map.core.chat import (
    QUESTION_POLICY,
    ChatSession,
    RetrievalGuidance,
    get_chat_agent,
)
from knowledge_map.core.retrieval import RetrievalCoordinator
from knowledge_map.schemas import (
    DeploymentKind,
    ModelDeployment,
    ModelRequestSettings,
    OpenRouterProviderPolicy,
)
from knowledge_map.schemas.query_preparation import (
    QueryRewriteProposal,
    QuestionAssessment,
)
from knowledge_map.schemas.retrieval import CoverageDescription
from knowledge_map.utils.models import get_chat_model

QUESTIONS = (
    "What should I read about AB 1751, the proposed $28 construction wage, and the disagreement between carpenters and other construction unions in California in 2026?",
    "What should I read about Assembly Bill 1751 in California’s 2025-2026 legislative session?",
)
AS_OF = datetime.fromisoformat("2026-10-13T02:43:39.486880+00:00")


def deployment(model="google/gemma-4-26b-a4b-it"):
    return ModelDeployment(
        kind=DeploymentKind.OPENROUTER,
        model=model,
        request_settings=ModelRequestSettings(
            temperature=0, timeout=60, max_attempts=2, rate_limit_wait_cap=15
        ),
        provider_policy=OpenRouterProviderPolicy(providers=("deepinfra/fp8",)),
    )


def completion(body, output):
    native = body.get("response_format", {}).get("type") == "json_schema"
    message = {"role": "assistant", "content": json.dumps(output) if native else None}
    if not native:
        message["tool_calls"] = [
            {
                "id": "result",
                "type": "function",
                "function": {
                    "name": body["tools"][0]["function"]["name"],
                    "arguments": json.dumps(output),
                },
            }
        ]
    return {
        "id": "native-assessment-test",
        "object": "chat.completion",
        "created": 0,
        "model": body["model"],
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": "stop" if native else "tool_calls",
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


async def assess(target, question, transport):
    model = get_chat_model(target, cache=False, transport=transport)
    agent = get_chat_agent(target, cache_model=False)
    original = agent.model
    session = ChatSession(
        question,
        chat_agent=agent,
        retrieval=cast(RetrievalCoordinator, None),
        coverage=CoverageDescription(entries=()),
        relevant_collection_ids=("calmatters",),
        as_of=AS_OF,
    )
    try:
        with agent.override(model=model):
            output = await session._assess(
                QueryRewriteProposal(question=question, relational=True)
            )
        return output, session._usage.requests
    finally:
        await model.client.close()
        await original.client.close()


def valid_assessment():
    return QuestionAssessment(status="allowed").model_dump(mode="json")


def assert_strict_native(body):
    assert body.get("response_format", {}).get("type") == "json_schema"
    specification = body["response_format"]["json_schema"]
    assert specification["strict"] is True
    assert not body.get("tools")
    schema = specification["schema"]
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])
    assert not any("default" in field for field in schema["properties"].values())
    output = valid_assessment()
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    assert validator.is_valid(output)
    assert not validator.is_valid({**output, "reading_order": "null"})
    assert not validator.is_valid({**output, "reading_order": None})
    assert not validator.is_valid({**output, "publication_date_from": "null"})
    assert not validator.is_valid({**output, "unexpected": True})
    assert not validator.is_valid(
        {key: value for key, value in output.items() if key != "reading_order"}
    )
    for name in ("publication_date_from", "publication_date_through"):
        assert {"type": "null"} in schema["properties"][name]["anyOf"]


@pytest.mark.parametrize("question", QUESTIONS)
def test_actual_gemma_session_assessment_requests_strict_native_schema(
    monkeypatch, question
):
    monkeypatch.setenv("OPENROUTER_API_KEY", "unused-native-assessment-key")
    requests = []

    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        assert_strict_native(body)
        context = json.loads(body["messages"][-1]["content"])
        assert context["question"] == question
        assert context["question_policy"] == QUESTION_POLICY
        assert context["as_of"] == AS_OF.isoformat()
        return httpx.Response(200, json=completion(body, valid_assessment()))

    output, count = asyncio.run(
        assess(deployment(), question, httpx.MockTransport(respond))
    )
    assert output.status == "allowed"
    assert output.reading_order == "relevance"
    assert output.publication_date_from is output.publication_date_through is None
    assert count == len(requests) == 1
    assert requests[0]["provider"]["only"] == ["deepinfra/fp8"]
    assert requests[0]["temperature"] == 0


@pytest.mark.parametrize("invalid", ["null", None, "invalid-order"])
def test_native_invalid_reading_order_still_fails_without_output_retry(
    monkeypatch, invalid
):
    monkeypatch.setenv("OPENROUTER_API_KEY", "unused-native-assessment-key")
    requests = []

    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        assert_strict_native(body)
        return httpx.Response(
            200, json=completion(body, {**valid_assessment(), "reading_order": invalid})
        )

    with pytest.raises(
        UnexpectedModelBehavior, match="Exceeded maximum output retries"
    ):
        asyncio.run(assess(deployment(), QUESTIONS[1], httpx.MockTransport(respond)))
    assert len(requests) == 1


@pytest.mark.parametrize(
    "target,expected_mode",
    [
        (deployment("google/gemini-3.1-flash-lite"), "tools"),
        (deployment("openai/gpt-4o-mini"), "tools"),
        (
            ModelDeployment(
                kind=DeploymentKind.LOCAL,
                model="gemma4:26b",
                endpoint="http://local.invalid/v1",
            ),
            "native",
        ),
    ],
)
def test_other_and_local_assessment_modes_are_unchanged(
    monkeypatch, target, expected_mode
):
    monkeypatch.setenv("OPENROUTER_API_KEY", "unused-native-assessment-key")
    requests = []

    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        if expected_mode == "native":
            assert body["response_format"]["type"] == "json_schema"
            assert body["response_format"]["json_schema"]["schema"]["required"] == [
                "status"
            ]
        else:
            assert body.get("response_format", {}).get("type") != "json_schema"
            assert body.get("tools")
        return httpx.Response(200, json=completion(body, valid_assessment()))

    output, count = asyncio.run(
        assess(target, QUESTIONS[1], httpx.MockTransport(respond))
    )
    assert output.status == "allowed"
    assert count == len(requests) == 1


def test_runtime_guidance_override_retains_original_tool_mode(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "unused-native-assessment-key")
    requests = []

    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        assert body.get("response_format", {}).get("type") != "json_schema"
        assert body.get("tools")
        return httpx.Response(
            200, json=completion(body, RetrievalGuidance().model_dump(mode="json"))
        )

    async def run():
        target = deployment()
        model = get_chat_model(
            target, cache=False, transport=httpx.MockTransport(respond)
        )
        agent = get_chat_agent(target, cache_model=False)
        original = agent.model
        try:
            with agent.override(model=model):
                output = await agent.run(
                    "Verified source evidence", output_type=RetrievalGuidance
                )
            assert isinstance(output.output, RetrievalGuidance)
            assert output.usage.requests == 1
        finally:
            await model.client.close()
            await original.client.close()

    asyncio.run(run())
    assert len(requests) == 1
