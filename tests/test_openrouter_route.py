"""The factory's OpenRouter provider policy at the real Agent seam."""

import json

import httpx
from pydantic_ai import Agent

from knowledge_map.schemas import (
    DeploymentKind,
    ModelDeployment,
    ModelRequestSettings,
    OpenRouterProviderPolicy,
)
from knowledge_map.utils.models import get_chat_model


def openrouter_deployment(**overrides) -> ModelDeployment:
    values = {
        "kind": DeploymentKind.OPENROUTER,
        "model": "openai/gpt-4o-mini",
        "request_settings": ModelRequestSettings(temperature=0.0),
        "provider_policy": OpenRouterProviderPolicy(
            providers=("google-ai-studio", "openai")
        ),
    }
    values.update(overrides)
    return ModelDeployment(**values)


def chat_completion() -> dict:
    return {
        "id": "chatcmpl-openrouter-route-test",
        "object": "chat.completion",
        "created": 0,
        "model": "openai/gpt-4o-mini",
        "provider": "openai/test",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "resolved"},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


def test_openrouter_request_carries_the_ordered_exclusive_policy_and_metadata(
    monkeypatch,
):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-openrouter-route-test")
    requests: list[tuple[httpx.Headers, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.headers, json.loads(request.content)))
        return httpx.Response(200, json=chat_completion())

    Agent(
        get_chat_model(
            openrouter_deployment(),
            transport=httpx.MockTransport(handler),
        ),
        output_type=str,
        defer_model_check=True,
    ).run_sync("Resolve it.")

    headers, body = requests[0]
    assert headers["x-openrouter-metadata"] == "enabled"
    assert body["model"] == "openai/gpt-4o-mini"
    assert "models" not in body
    assert body["provider"] == {
        "order": ["google-ai-studio", "openai"],
        "only": ["google-ai-studio", "openai"],
        "allow_fallbacks": True,
        "require_parameters": True,
    }


def test_openrouter_cache_identity_includes_route_model_and_settings_but_not_key(
    monkeypatch,
):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-first")
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=chat_completion()))
    deployment = openrouter_deployment()

    equivalent = get_chat_model(deployment, transport=transport)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-second")
    same_route = get_chat_model(deployment, transport=transport)
    different_route = get_chat_model(
        openrouter_deployment(
            provider_policy=OpenRouterProviderPolicy(
                providers=("openai", "google-ai-studio")
            )
        ),
        transport=transport,
    )
    different_model = get_chat_model(
        openrouter_deployment(model="openai/gpt-4.1-mini"),
        transport=transport,
    )
    different_settings = get_chat_model(
        openrouter_deployment(
            request_settings=ModelRequestSettings(temperature=0.7)
        ),
        transport=transport,
    )

    assert equivalent is same_route
    assert equivalent is not different_route
    assert equivalent is not different_model
    assert equivalent is not different_settings
    assert equivalent.client.api_key == "sk-first"
