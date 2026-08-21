"""The model factory's retrying HTTP client, observed through a real agent call.

Every assertion here runs a real ``Agent`` against a model the factory built,
with an ``httpx.MockTransport`` standing in for the Ollama host.  That is the
highest point at which transport retry is observable, and it exercises the real
provider wiring rather than a client in isolation.
"""

import asyncio

import httpx
import pytest
from pydantic_ai import Agent

from knowledge_map.config import TransportSettings, settings
from knowledge_map.utils.models import get_ollama_model


def chat_completion(content: str) -> dict:
    """A minimal OpenAI-compatible chat completion body."""

    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 0,
        "model": "test-model",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


@pytest.fixture
def recorded_waits(monkeypatch):
    """Record every retry wait and take none of them."""

    waits: list[float] = []
    real_sleep = asyncio.sleep

    async def recording_sleep(delay, *args, **kwargs):
        waits.append(delay)
        return await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", recording_sleep)
    return waits


def agent_for(transport: httpx.MockTransport, **kwargs) -> Agent:
    model = get_ollama_model("test-model", transport=transport, **kwargs)
    return Agent(model, output_type=str, defer_model_check=True)


def test_rate_limited_request_is_retried_after_the_header_delay(recorded_waits):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(
                429,
                headers={"Retry-After": "7"},
                json={"error": {"message": "rate limited"}},
            )
        return httpx.Response(200, json=chat_completion("resolved"))

    agent = agent_for(httpx.MockTransport(handler))
    result = agent.run_sync("Resolve the references.")

    assert result.output == "resolved"
    assert len(requests) == 2
    assert 7.0 in recorded_waits


def test_transport_errors_are_retried_until_the_attempt_count_is_exhausted(
    recorded_waits,
):
    attempts: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(request)
        raise httpx.ConnectError("connection reset by peer")

    transport_settings = TransportSettings(max_attempts=2)
    agent = agent_for(
        httpx.MockTransport(handler), transport_settings=transport_settings
    )

    with pytest.raises(Exception) as exc_info:
        agent.run_sync("Resolve the references.")

    assert len(attempts) == transport_settings.max_attempts
    assert any(
        isinstance(cause, httpx.ConnectError)
        for cause in _causes(exc_info.value)
    )


def _causes(error: BaseException) -> list[BaseException]:
    """Every exception in the chain, so a re-raise can be found under a wrapper."""

    chain: list[BaseException] = []
    current: BaseException | None = error
    while current is not None and current not in chain:
        chain.append(current)
        current = current.__cause__ or current.__context__
    return chain


def test_rate_limit_wait_is_capped_by_the_configured_maximum(recorded_waits):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(
                429,
                headers={"Retry-After": "600"},
                json={"error": {"message": "rate limited"}},
            )
        return httpx.Response(200, json=chat_completion("resolved"))

    agent = agent_for(
        httpx.MockTransport(handler),
        transport_settings=TransportSettings(rate_limit_wait_cap=30),
    )
    result = agent.run_sync("Resolve the references.")

    assert result.output == "resolved"
    assert max(recorded_waits) == 30


def test_transport_settings_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("LLM_TRANSPORT_MAX_ATTEMPTS", "7")
    monkeypatch.setenv("LLM_TRANSPORT_RATE_LIMIT_WAIT_CAP", "45")
    monkeypatch.setenv("LLM_TRANSPORT_REQUEST_TIMEOUT", "90.5")

    transport_settings = TransportSettings()

    assert transport_settings.max_attempts == 7
    assert transport_settings.rate_limit_wait_cap == 45
    assert transport_settings.request_timeout == 90.5


def test_transport_settings_have_defaults():
    assert settings.transport.max_attempts == 3
    assert settings.transport.rate_limit_wait_cap == 120
    assert settings.transport.request_timeout == 600.0


def test_repeated_construction_shares_one_model_and_connection_pool():
    first = get_ollama_model("test-model", "OLLAMA_MODEL_COREFERENCE")
    second = get_ollama_model("test-model", "OLLAMA_MODEL_COREFERENCE")

    assert first is second


def test_a_different_model_name_gets_its_own_client(monkeypatch):
    first = get_ollama_model("test-model-a")
    second = get_ollama_model("test-model-b")

    assert first is not second


def test_the_ollama_null_content_patch_applies_to_every_model():
    from pydantic_ai.models.openai import OpenAIChatModel

    get_ollama_model("test-model")

    assert (
        OpenAIChatModel._MapModelResponseContext._into_message_param.__name__
        == "_into_message_param_with_empty_content"
    )
