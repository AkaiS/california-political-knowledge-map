"""The model factory's native OpenRouter deployment seam."""

import json

import httpx
import pytest
from pydantic_ai import Agent
from pydantic_ai.models.openrouter import OpenRouterModel

from knowledge_map.config import TransportSettings
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
        "request_settings": ModelRequestSettings(
            temperature=0.25,
            top_p=0.85,
            top_k=40,
            thinking=True,
            max_tokens=128,
            timeout=7.5,
        ),
        "provider_policy": OpenRouterProviderPolicy(providers=("openai",)),
    }
    values.update(overrides)
    return ModelDeployment(**values)


def chat_completion(content: str) -> dict:
    """A minimal OpenRouter-compatible chat completion body."""

    return {
        "id": "chatcmpl-openrouter-test",
        "object": "chat.completion",
        "created": 0,
        "model": "openai/gpt-4o-mini",
        "provider": "openai/test",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


def test_openrouter_deployment_builds_a_real_agent_with_native_provider(
    monkeypatch,
):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-openrouter-test")
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == (
            "https://openrouter.ai/api/v1/chat/completions"
        )
        assert request.headers["authorization"] == "Bearer sk-openrouter-test"
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json=chat_completion("resolved"))

    deployment = openrouter_deployment()
    model = get_chat_model(
        deployment,
        transport=httpx.MockTransport(handler),
    )

    result = Agent(model, output_type=str, defer_model_check=True).run_sync(
        "Resolve the references."
    )

    assert result.output == "resolved"
    assert isinstance(model, OpenRouterModel)
    assert model.system == "openrouter"
    assert model.base_url.rstrip("/") == "https://openrouter.ai/api/v1"
    assert bodies[0]["model"] == deployment.model


def test_openrouter_request_has_one_model_and_shared_request_settings(
    monkeypatch,
):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-openrouter-test")
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json=chat_completion("resolved"))

    deployment = openrouter_deployment()
    model = get_chat_model(
        deployment,
        transport=httpx.MockTransport(handler),
    )
    Agent(model, output_type=str, defer_model_check=True).run_sync("Resolve it.")

    body = bodies[0]
    assert body["model"] == deployment.model
    assert "models" not in body
    assert body["temperature"] == 0.25
    assert body["top_p"] == 0.85
    assert body["top_k"] == 40
    assert body["max_tokens"] == 128
    assert body["reasoning"] == {"effort": "medium", "enabled": True}
    assert model.settings["timeout"] == 7.5


def test_openrouter_uses_native_profile_without_local_message_workarounds(
    monkeypatch,
):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-openrouter-test")
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json=chat_completion("resolved"))

    model = get_chat_model(
        openrouter_deployment(),
        transport=httpx.MockTransport(handler),
    )
    Agent(model, output_type=str, defer_model_check=True).run_sync("Resolve it.")

    assert model.profile["openai_chat_thinking_field"] == "reasoning"
    assert "chat_template_kwargs" not in bodies[0]


def test_typed_openrouter_deployment_rejects_out_of_band_transport_settings(
    monkeypatch,
):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-openrouter-test")

    with pytest.raises(ValueError, match="must be part of its request_settings"):
        get_chat_model(
            openrouter_deployment(),
            transport_settings=TransportSettings(request_timeout=11.5),
            transport=httpx.MockTransport(lambda request: None),
        )


def test_openrouter_api_key_is_provider_state_not_deployment_identity(monkeypatch):
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json=chat_completion("resolved"))
    )
    deployment = openrouter_deployment()

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-first")
    first = get_chat_model(deployment, transport=transport)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-second")
    second = get_chat_model(deployment, transport=transport)

    assert first is second
    assert first.client.api_key == "sk-first"
    assert "sk-first" not in deployment.model_dump_json()


def test_openrouter_cache_identity_includes_deployment_request_timeout(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-openrouter-test")
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json=chat_completion("resolved"))
    )
    first_deployment = openrouter_deployment(
        request_settings=openrouter_deployment().request_settings.model_copy(
            update={"timeout": 11.5}
        )
    )
    second_deployment = openrouter_deployment(
        request_settings=openrouter_deployment().request_settings.model_copy(
            update={"timeout": 22.0}
        )
    )

    first = get_chat_model(first_deployment, transport=transport)
    second = get_chat_model(second_deployment, transport=transport)

    assert first is not second
    assert first.settings["timeout"] == 11.5
    assert second.settings["timeout"] == 22.0


@pytest.mark.parametrize(
    ("request_settings", "expected_reasoning"),
    [
        (
            ModelRequestSettings(reasoning_effort="high"),
            {"effort": "high"},
        ),
        (
            ModelRequestSettings(thinking=False),
            {"effort": "none"},
        ),
    ],
)
def test_openrouter_reasoning_settings_reach_the_request(
    monkeypatch,
    request_settings: ModelRequestSettings,
    expected_reasoning: dict[str, str],
):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-openrouter-test")
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json=chat_completion("resolved"))

    Agent(
        get_chat_model(
            openrouter_deployment(request_settings=request_settings),
            transport=httpx.MockTransport(handler),
        ),
        output_type=str,
        defer_model_check=True,
    ).run_sync("Resolve it.")

    assert bodies[0]["reasoning"] == expected_reasoning
