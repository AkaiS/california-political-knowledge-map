"""The model factory's native OpenRouter deployment seam."""

import json

import httpx
import pytest
from logfire.testing import TestExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from pydantic_ai import Agent
from pydantic_ai.models.instrumented import InstrumentationSettings
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


def test_openrouter_route_is_emitted_as_structured_logfire_data(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-openrouter-test")
    events: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        "knowledge_map.utils.models.logfire.info",
        lambda message, **attributes: events.append((message, attributes)),
    )

    model = get_chat_model(
        openrouter_deployment(),
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=chat_completion("resolved"))
        ),
    )
    Agent(
        model,
        name="openrouter_observability_test",
        output_type=str,
        defer_model_check=True,
    ).run_sync("Resolve it.")

    assert events == [
        (
            "OpenRouter model request completed",
            {
                "deployment": "openrouter",
                "requested_model": "openai/gpt-4o-mini",
                "returned_model": "openai/gpt-4o-mini",
                "downstream_provider": "openai/test",
                "is_byok": None,
                "generation_id": "chatcmpl-openrouter-test",
                "route_attempts": None,
                "application_attempts": 1,
                "provider_order": ["openai"],
                "allow_fallbacks": True,
                "charged_cost": None,
                "upstream_cost": None,
            },
        )
    ]


def test_openrouter_completion_event_keeps_operational_route_and_cost_facts(
    monkeypatch,
):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-openrouter-test")
    events: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        "knowledge_map.utils.models.logfire.info",
        lambda message, **attributes: events.append((message, attributes)),
    )
    completion = chat_completion("resolved")
    completion["usage"].update(
        {
            "is_byok": True,
            "cost": 0.0012,
            "cost_details": {"upstream_inference_cost": 0.0008},
        }
    )
    completion["openrouter_metadata"] = {
        "attempts": [
            {"provider": "openai/first", "status": 429},
            {"provider": "openai/test", "status": 200},
        ]
    }

    model = get_chat_model(
        openrouter_deployment(),
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=completion)
        ),
    )
    Agent(
        model,
        name="openrouter_completion_event_test",
        output_type=str,
        defer_model_check=True,
    ).run_sync("Resolve it.")

    message, attributes = events[0]
    assert message == "OpenRouter model request completed"
    assert attributes["is_byok"] is True
    assert attributes["generation_id"] == "chatcmpl-openrouter-test"
    assert attributes["route_attempts"] == 2
    assert attributes["application_attempts"] == 1
    assert attributes["charged_cost"] == "0.0012"
    assert attributes["upstream_cost"] == "0.0008"


def test_observed_openrouter_provider_joins_standard_model_request_telemetry(
    monkeypatch,
):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-openrouter-test")
    exporter = TestExporter()
    tracer_provider = TracerProvider()
    tracer_provider.add_span_processor(SimpleSpanProcessor(exporter))

    model = get_chat_model(
        openrouter_deployment(),
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=chat_completion("resolved"))
        ),
    )
    agent = Agent(
        model,
        name="openrouter_telemetry_test",
        output_type=str,
        defer_model_check=True,
    )
    agent.instrument = InstrumentationSettings(tracer_provider=tracer_provider)
    agent.run_sync("Resolve it.")

    model_request_span = next(
        span
        for span in exporter.exported_spans_as_dict(parse_json_attributes=True)
        if span["name"] == "chat openai/gpt-4o-mini"
    )
    attributes = model_request_span["attributes"]
    assert attributes["gen_ai.response.downstream_provider"] == "openai/test"
    assert attributes["gen_ai.request.model"] == "openai/gpt-4o-mini"
    assert attributes["gen_ai.response.model"] == "openai/gpt-4o-mini"
    assert attributes["gen_ai.response.id"] == "chatcmpl-openrouter-test"
    assert attributes["gen_ai.usage.input_tokens"] == 1
    assert attributes["gen_ai.usage.output_tokens"] == 1
    assert attributes["operation.cost"] > 0
    assert attributes["gen_ai.input.messages"][0]["role"] == "user"
    assert attributes["gen_ai.output.messages"][0]["role"] == "assistant"


def test_missing_openrouter_provider_stays_absent_from_model_request_telemetry(
    monkeypatch,
):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-openrouter-test")
    exporter = TestExporter()
    tracer_provider = TracerProvider()
    tracer_provider.add_span_processor(SimpleSpanProcessor(exporter))
    completion = chat_completion("resolved")
    completion.pop("provider")

    model = get_chat_model(
        openrouter_deployment(),
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=completion)
        ),
    )
    agent = Agent(
        model,
        name="openrouter_missing_provider_telemetry_test",
        output_type=str,
        defer_model_check=True,
    )
    agent.instrument = InstrumentationSettings(tracer_provider=tracer_provider)
    agent.run_sync("Resolve it.")

    model_request_span = next(
        span
        for span in exporter.exported_spans_as_dict()
        if span["name"] == "chat openai/gpt-4o-mini"
    )
    assert "gen_ai.response.downstream_provider" not in model_request_span["attributes"]


def test_local_model_request_telemetry_does_not_invent_a_downstream_provider():
    exporter = TestExporter()
    tracer_provider = TracerProvider()
    tracer_provider.add_span_processor(SimpleSpanProcessor(exporter))
    deployment = ModelDeployment(
        kind=DeploymentKind.LOCAL,
        model="local/test-model",
        endpoint="http://llama.test/v1",
        request_settings=ModelRequestSettings(max_attempts=1),
    )

    model = get_chat_model(
        deployment,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=chat_completion("resolved"))
        ),
    )
    agent = Agent(
        model,
        name="local_telemetry_test",
        output_type=str,
        defer_model_check=True,
    )
    agent.instrument = InstrumentationSettings(tracer_provider=tracer_provider)
    agent.run_sync("Resolve it.")

    model_request_span = next(
        span
        for span in exporter.exported_spans_as_dict()
        if span["name"] == "chat local/test-model"
    )
    assert "gen_ai.response.downstream_provider" not in model_request_span["attributes"]
    assert model_request_span["attributes"]["gen_ai.provider.name"] == "openai"


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
