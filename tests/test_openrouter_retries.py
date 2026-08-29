"""Request-local OpenRouter retry behavior at the real Agent seam."""

import asyncio

import httpx
import pytest
from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelAPIError, ModelHTTPError

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
            temperature=0.0,
            max_attempts=2,
        ),
        "provider_policy": OpenRouterProviderPolicy(providers=("openai",)),
    }
    values.update(overrides)
    return ModelDeployment(**values)


def chat_completion() -> dict:
    return {
        "id": "chatcmpl-openrouter-retry-test",
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


def error_response(status_code: int) -> httpx.Response:
    return httpx.Response(
        status_code,
        json={
            "error": {
                "message": "temporary upstream failure",
                "type": "server_error",
                "code": status_code,
            }
        },
    )


class TrackingTransport(httpx.AsyncBaseTransport):
    def __init__(self) -> None:
        self.closed = False

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=chat_completion(), request=request)

    async def aclose(self) -> None:
        self.closed = True


class TrackingStream(httpx.AsyncByteStream):
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.closed = False

    async def __aiter__(self):
        yield self.content

    async def aclose(self) -> None:
        self.closed = True


def test_retryable_server_response_retries_the_same_agent_request(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-openrouter-retry-test")
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return error_response(503)
        return httpx.Response(200, json=chat_completion())

    result = Agent(
        get_chat_model(
            openrouter_deployment(),
            transport=httpx.MockTransport(handler),
        ),
        output_type=str,
        defer_model_check=True,
    ).run_sync("Resolve it.")

    assert result.output == "resolved"
    assert len(requests) == 2
    assert requests[0].content == requests[1].content


def test_transport_error_retries_at_the_request_boundary(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-openrouter-retry-test")
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            raise httpx.ConnectError("connection reset", request=request)
        return httpx.Response(200, json=chat_completion())

    result = Agent(
        get_chat_model(
            openrouter_deployment(),
            transport=httpx.MockTransport(handler),
        ),
        output_type=str,
        defer_model_check=True,
    ).run_sync("Resolve it.")

    assert result.output == "resolved"
    assert len(requests) == 2


def test_exhausted_retryable_response_is_reraised_through_the_agent(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-openrouter-retry-test")
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return error_response(503)

    with pytest.raises(ModelHTTPError) as exc_info:
        Agent(
            get_chat_model(
                openrouter_deployment(),
                transport=httpx.MockTransport(handler),
            ),
            output_type=str,
            defer_model_check=True,
        ).run_sync("Resolve it.")

    assert exc_info.value.status_code == 503
    assert len(requests) == 2


def test_exhausted_transport_error_is_reraised_through_the_agent(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-openrouter-retry-test")
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        raise httpx.ConnectError("connection reset", request=request)

    with pytest.raises(ModelAPIError):
        Agent(
            get_chat_model(
                openrouter_deployment(),
                transport=httpx.MockTransport(handler),
            ),
            output_type=str,
            defer_model_check=True,
        ).run_sync("Resolve it.")

    assert len(requests) == 2


def test_openrouter_agent_client_closes_the_wrapped_transport(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-openrouter-retry-test")
    transport = TrackingTransport()
    model = get_chat_model(openrouter_deployment(), transport=transport)

    async def run_and_close_client():
        try:
            return await Agent(
                model,
                output_type=str,
                defer_model_check=True,
            ).run("Resolve it.")
        finally:
            await model.provider.client.close()

    result = asyncio.run(run_and_close_client())

    assert result.output == "resolved"
    assert transport.closed


def test_retry_closes_the_intermediate_response_before_retry(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-openrouter-retry-test")
    first_response_stream = TrackingStream(b"temporary upstream failure")
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(
                503,
                stream=first_response_stream,
                request=request,
            )
        return httpx.Response(200, json=chat_completion(), request=request)

    result = Agent(
        get_chat_model(
            openrouter_deployment(),
            transport=httpx.MockTransport(handler),
        ),
        output_type=str,
        defer_model_check=True,
    ).run_sync("Resolve it.")

    assert result.output == "resolved"
    assert first_response_stream.closed


@pytest.mark.parametrize("status_code", [400, 401, 402, 403, 404, 422])
def test_nonretryable_openrouter_responses_make_one_attempt(
    monkeypatch,
    status_code: int,
):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-openrouter-retry-test")
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return error_response(status_code)

    with pytest.raises(ModelHTTPError) as exc_info:
        Agent(
            get_chat_model(
                openrouter_deployment(),
                transport=httpx.MockTransport(handler),
            ),
            output_type=str,
            defer_model_check=True,
        ).run_sync("Resolve it.")

    assert exc_info.value.status_code == status_code
    assert len(requests) == 1


@pytest.mark.parametrize("status_code", [500, 502, 504, 524, 529])
def test_retryable_non_rate_server_responses_use_the_attempt_bound(
    monkeypatch,
    status_code: int,
):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-openrouter-retry-test")
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return error_response(status_code)

    with pytest.raises(ModelHTTPError) as exc_info:
        Agent(
            get_chat_model(
                openrouter_deployment(),
                transport=httpx.MockTransport(handler),
            ),
            output_type=str,
            defer_model_check=True,
        ).run_sync("Resolve it.")

    assert exc_info.value.status_code == status_code
    assert len(requests) == 2
