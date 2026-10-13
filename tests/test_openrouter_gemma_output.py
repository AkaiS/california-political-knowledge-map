"""OpenRouter Gemma assessment output at the model factory's HTTP boundary."""

import asyncio
import copy
import json

import httpx
import pytest
from jsonschema import Draft202012Validator
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.models.openrouter import OpenRouterModel
from pydantic_ai.profiles import InlineDefsJsonSchemaTransformer

from knowledge_map.core.chat import QUESTION_POLICY, get_chat_agent
from knowledge_map.schemas import (
    DeploymentKind,
    ModelDeployment,
    ModelRequestSettings,
    OpenRouterProviderPolicy,
)
from knowledge_map.schemas.query_preparation import QuestionAssessment
from knowledge_map.utils.models import get_chat_model

QUESTION = (
    "What should I read about AB 1751, the proposed $28 construction wage, and "
    "the disagreement between carpenters and other construction unions in California in 2026?"
)


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
    return {
        "id": "assessment-output-test",
        "object": "chat.completion",
        "created": 0,
        "model": body["model"],
        "provider": "DeepInfra",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "assessment-result",
                            "type": "function",
                            "function": {
                                "name": body["tools"][0]["function"]["name"],
                                "arguments": json.dumps(output),
                            },
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


async def assess(model, transport):
    target = deployment(model)
    factory_model = get_chat_model(target, cache=False, transport=transport)
    agent = get_chat_agent(target, cache_model=False)
    original = agent.model
    try:
        with agent.override(model=factory_model):
            return await agent.run(
                json.dumps(
                    {
                        "as_of": "2026-10-13T01:52:10.841169Z",
                        "current_date": "2026-10-13",
                        "question": QUESTION,
                        "coverage": {"entries": []},
                        "question_policy": QUESTION_POLICY,
                    }
                )
            )
    finally:
        await factory_model.client.close()
        await original.client.close()


@pytest.mark.parametrize(
    "model", ["google/gemma-4-26b-a4b-it", "~google/gemma-4-26b-a4b-it:free"]
)
def test_openrouter_gemma_assessment_can_return_real_null_dates(monkeypatch, model):
    monkeypatch.setenv("OPENROUTER_API_KEY", "unused-output-test-key")
    requests = []

    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        fields = body["tools"][0]["function"]["parameters"]["properties"]
        for name in ("publication_date_from", "publication_date_through"):
            assert Draft202012Validator(fields[name]).is_valid(None), (
                "The request must permit the same JSON null accepted by QuestionAssessment"
            )
        return httpx.Response(
            200,
            json=completion(
                body,
                {
                    "status": "allowed",
                    "publication_date_from": None,
                    "publication_date_through": None,
                },
            ),
        )

    result = asyncio.run(assess(model, httpx.MockTransport(respond)))
    assert result.output.status == "allowed"
    assert result.output.publication_date_from is None
    assert result.output.publication_date_through is None
    assert result.usage.requests == len(requests) == 1
    assert requests[0]["provider"]["only"] == ["deepinfra/fp8"]


@pytest.mark.parametrize(
    "model", ["google/gemma-4-26b-a4b-it", "~google/gemma-4-26b-a4b-it:free"]
)
def test_gemma_preserves_every_other_inferred_profile_field(monkeypatch, model):
    monkeypatch.setenv("OPENROUTER_API_KEY", "unused-output-test-key")

    async def compare():
        built = get_chat_model(
            deployment(model),
            cache=False,
            transport=httpx.MockTransport(lambda _: None),
        )
        baseline = OpenRouterModel(
            model, provider=built.provider, settings=built.settings
        )
        try:
            actual, original = dict(built.profile), dict(baseline.profile)
            actual.pop("json_schema_transformer")
            original.pop("json_schema_transformer")
            assert actual == original
        finally:
            await built.client.close()

    asyncio.run(compare())


@pytest.mark.parametrize(
    "model",
    [
        "google/gemini-3.1-flash-lite",
        "openai/gpt-4o-mini",
        "meta-llama/llama-3.3-70b-instruct",
    ],
)
def test_other_openrouter_models_preserve_the_complete_provider_profile(
    monkeypatch, model
):
    monkeypatch.setenv("OPENROUTER_API_KEY", "unused-output-test-key")

    async def compare():
        built = get_chat_model(
            deployment(model),
            cache=False,
            transport=httpx.MockTransport(lambda _: None),
        )
        baseline = OpenRouterModel(
            model, provider=built.provider, settings=built.settings
        )
        try:
            assert built.profile == baseline.profile
        finally:
            await built.client.close()

    asyncio.run(compare())


def test_local_gemma_keeps_inlined_definitions_and_real_null_dates():
    async def check():
        local = ModelDeployment(
            kind=DeploymentKind.LOCAL,
            model="gemma4:26b",
            endpoint="http://local.invalid/v1",
        )
        built = get_chat_model(
            local, cache=False, transport=httpx.MockTransport(lambda _: None)
        )
        try:
            transformer = built.profile["json_schema_transformer"]
            assert transformer is InlineDefsJsonSchemaTransformer
            schema = transformer(
                copy.deepcopy(QuestionAssessment.model_json_schema())
            ).walk()
            for name in ("publication_date_from", "publication_date_through"):
                assert Draft202012Validator(schema["properties"][name]).is_valid(None)
        finally:
            await built.client.close()

    asyncio.run(check())


@pytest.mark.parametrize("invalid", ["", "null"])
def test_bad_date_strings_still_fail_assessment_without_output_retry(
    monkeypatch, invalid
):
    monkeypatch.setenv("OPENROUTER_API_KEY", "unused-output-test-key")
    requests = []

    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        return httpx.Response(
            200,
            json=completion(
                body,
                {
                    "status": "allowed",
                    "publication_date_from": invalid,
                    "publication_date_through": invalid,
                },
            ),
        )

    with pytest.raises(
        UnexpectedModelBehavior, match="Exceeded maximum output retries"
    ):
        asyncio.run(assess("google/gemma-4-26b-a4b-it", httpx.MockTransport(respond)))
    assert len(requests) == 1
