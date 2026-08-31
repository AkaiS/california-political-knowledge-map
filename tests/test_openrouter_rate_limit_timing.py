"""OpenRouter 429 timing at the real Agent seam."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import format_datetime

import httpx
import pytest
from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelHTTPError

from knowledge_map.schemas import (
    DeploymentKind,
    ModelDeployment,
    ModelRequestSettings,
    OpenRouterProviderPolicy,
)
from knowledge_map.utils.models import (
    OpenRouterAdmissionGate,
    OpenRouterRetryHooks,
    get_chat_model,
)


@dataclass
class ControlledClock:
    now_value: float = 1_700_000_000.0
    sleeps: list[float] = field(default_factory=list)
    responses_closed_before_sleep: list[bool] = field(default_factory=list)
    response_to_check: httpx.Response | None = None

    def now(self) -> float:
        return self.now_value

    async def sleep(self, delay: float) -> None:
        self.responses_closed_before_sleep.append(
            self.response_to_check.is_closed
            if self.response_to_check is not None
            else False
        )
        self.sleeps.append(delay)
        self.now_value += delay


def openrouter_deployment(**overrides) -> ModelDeployment:
    values = {
        "kind": DeploymentKind.OPENROUTER,
        "model": "openai/gpt-4o-mini",
        "request_settings": ModelRequestSettings(
            temperature=0.0,
            max_attempts=2,
            rate_limit_wait_cap=120.0,
        ),
        "provider_policy": OpenRouterProviderPolicy(providers=("openai",)),
    }
    values.update(overrides)
    return ModelDeployment(**values)


def chat_completion() -> dict:
    return {
        "id": "chatcmpl-openrouter-rate-limit-test",
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


def retry_hooks_for(clock, *, jitter) -> OpenRouterRetryHooks:
    return OpenRouterRetryHooks(
        now=clock.now,
        sleep=clock.sleep,
        jitter=jitter,
        admission_gate=OpenRouterAdmissionGate(),
    )


class TrackingStream(httpx.AsyncByteStream):
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.closed = False

    async def __aiter__(self):
        yield self.content

    async def aclose(self) -> None:
        self.closed = True


def test_valid_reset_header_wins_and_releases_response_before_wait(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-openrouter-rate-limit-test")
    clock = ControlledClock()
    failed_response_stream = TrackingStream(b"rate limited")
    failed_response = httpx.Response(
        429,
        headers={
            "X-RateLimit-Reset": str(clock.now_value + 37),
            "Retry-After": "3",
        },
        stream=failed_response_stream,
    )
    clock.response_to_check = failed_response
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return failed_response
        return httpx.Response(200, json=chat_completion())

    result = Agent(
        get_chat_model(
            openrouter_deployment(),
            transport=httpx.MockTransport(handler),
            openrouter_retry_hooks=retry_hooks_for(
                clock, jitter=lambda upper_bound: upper_bound
            ),
        ),
        output_type=str,
        defer_model_check=True,
    ).run_sync("Resolve it.")

    assert result.output == "resolved"
    assert len(requests) == 2
    assert requests[0].content == requests[1].content
    assert clock.sleeps == [37.0]
    assert clock.responses_closed_before_sleep == [True]
    assert failed_response_stream.closed


def test_retry_after_wins_when_reset_header_is_invalid(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-openrouter-rate-limit-test")
    clock = ControlledClock()
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(
                429,
                headers={
                    "X-RateLimit-Reset": "not-a-timestamp",
                    "Retry-After": "11",
                },
                json={"error": {"message": "rate limited", "code": 429}},
            )
        return httpx.Response(200, json=chat_completion())

    result = Agent(
        get_chat_model(
            openrouter_deployment(),
            transport=httpx.MockTransport(handler),
            openrouter_retry_hooks=retry_hooks_for(
                clock, jitter=lambda upper_bound: upper_bound
            ),
        ),
        output_type=str,
        defer_model_check=True,
    ).run_sync("Resolve it.")

    assert result.output == "resolved"
    assert len(requests) == 2
    assert clock.sleeps == [11.0]


@pytest.mark.parametrize(
    "date_format",
    (
        None,
        "%A, %d-%b-%y %H:%M:%S GMT",
        "%a %b %d %H:%M:%S %Y",
    ),
)
def test_retry_after_http_date_is_supported(monkeypatch, date_format):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-openrouter-rate-limit-test")
    clock = ControlledClock()
    retry_at = datetime.fromtimestamp(clock.now_value + 11, UTC)
    retry_after = (
        format_datetime(retry_at, usegmt=True)
        if date_format is None
        else retry_at.strftime(date_format)
    )
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(
                429,
                headers={"Retry-After": retry_after},
                json={"error": {"message": "rate limited", "code": 429}},
            )
        return httpx.Response(200, json=chat_completion())

    result = Agent(
        get_chat_model(
            openrouter_deployment(),
            transport=httpx.MockTransport(handler),
            openrouter_retry_hooks=retry_hooks_for(
                clock, jitter=lambda upper_bound: upper_bound
            ),
        ),
        output_type=str,
        defer_model_check=True,
    ).run_sync("Resolve it.")

    assert result.output == "resolved"
    assert len(requests) == 2
    assert clock.sleeps == [11.0]


def test_invalid_timing_headers_use_jittered_exponential_backoff(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-openrouter-rate-limit-test")
    clock = ControlledClock()
    malformed_http_date = datetime.fromtimestamp(
        clock.now_value + 11, UTC
    ).strftime("%d %b %Y %H:%M:%S")
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(
                429,
                headers={
                    "X-RateLimit-Reset": str(clock.now_value - 1),
                    "Retry-After": malformed_http_date,
                },
                json={"error": {"message": "rate limited", "code": 429}},
            )
        return httpx.Response(200, json=chat_completion())

    result = Agent(
        get_chat_model(
            openrouter_deployment(),
            transport=httpx.MockTransport(handler),
            openrouter_retry_hooks=retry_hooks_for(
                clock, jitter=lambda upper_bound: upper_bound / 2
            ),
        ),
        output_type=str,
        defer_model_check=True,
    ).run_sync("Resolve it.")

    assert result.output == "resolved"
    assert len(requests) == 2
    assert clock.sleeps == [0.5]


def test_reset_header_accepts_openrouter_millisecond_epoch(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-openrouter-rate-limit-test")
    clock = ControlledClock()
    reset_at = clock.now_value + 23
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(
                429,
                headers={
                    "X-RateLimit-Reset": str(int(reset_at * 1_000)),
                },
                json={"error": {"message": "rate limited", "code": 429}},
            )
        return httpx.Response(200, json=chat_completion())

    result = Agent(
        get_chat_model(
            openrouter_deployment(),
            transport=httpx.MockTransport(handler),
            openrouter_retry_hooks=retry_hooks_for(
                clock, jitter=lambda upper_bound: upper_bound
            ),
        ),
        output_type=str,
        defer_model_check=True,
    ).run_sync("Resolve it.")

    assert result.output == "resolved"
    assert len(requests) == 2
    assert clock.sleeps == [23.0]


def test_server_timing_is_capped_before_waiting(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-openrouter-rate-limit-test")
    clock = ControlledClock()
    requests: list[httpx.Request] = []
    deployment = openrouter_deployment(
        request_settings=ModelRequestSettings(
            temperature=0.0,
            max_attempts=2,
            rate_limit_wait_cap=5.0,
        )
    )

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(
                429,
                headers={
                    "X-RateLimit-Reset": str(clock.now_value + 60),
                    "Retry-After": "20",
                },
                json={"error": {"message": "rate limited", "code": 429}},
            )
        return httpx.Response(200, json=chat_completion())

    result = Agent(
        get_chat_model(
            deployment,
            transport=httpx.MockTransport(handler),
            openrouter_retry_hooks=retry_hooks_for(
                clock, jitter=lambda upper_bound: upper_bound
            ),
        ),
        output_type=str,
        defer_model_check=True,
    ).run_sync("Resolve it.")

    assert result.output == "resolved"
    assert len(requests) == 2
    assert clock.sleeps == [5.0]


def test_rate_limit_exhaustion_uses_the_attempt_bound_without_wall_sleep(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-openrouter-rate-limit-test")
    clock = ControlledClock()
    requests: list[httpx.Request] = []
    deployment = openrouter_deployment(
        request_settings=ModelRequestSettings(
            temperature=0.0,
            max_attempts=3,
            rate_limit_wait_cap=120.0,
        )
    )

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            429,
            headers={"Retry-After": "4"},
            json={"error": {"message": "rate limited", "code": 429}},
        )

    with pytest.raises(ModelHTTPError) as exc_info:
        Agent(
            get_chat_model(
                deployment,
                transport=httpx.MockTransport(handler),
                openrouter_retry_hooks=retry_hooks_for(
                    clock, jitter=lambda upper_bound: upper_bound
                ),
            ),
            output_type=str,
            defer_model_check=True,
        ).run_sync("Resolve it.")

    assert exc_info.value.status_code == 429
    assert len(requests) == 3
    assert clock.sleeps == [4.0, 4.0]


def test_fallback_backoff_is_exponential_and_capped(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-openrouter-rate-limit-test")
    clock = ControlledClock()
    requests: list[httpx.Request] = []
    deployment = openrouter_deployment(
        request_settings=ModelRequestSettings(
            temperature=0.0,
            max_attempts=5,
            rate_limit_wait_cap=5.0,
        )
    )

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            429,
            json={"error": {"message": "rate limited", "code": 429}},
        )

    with pytest.raises(ModelHTTPError):
        Agent(
            get_chat_model(
                deployment,
                transport=httpx.MockTransport(handler),
                openrouter_retry_hooks=retry_hooks_for(
                    clock, jitter=lambda upper_bound: upper_bound
                ),
            ),
            output_type=str,
            defer_model_check=True,
        ).run_sync("Resolve it.")

    assert len(requests) == 5
    assert clock.sleeps == [1.0, 2.0, 4.0, 5.0]


def test_deployment_settings_bound_openrouter_rate_limit_attempts(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-openrouter-rate-limit-test")
    clock = ControlledClock()
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            429,
            headers={"Retry-After": "0"},
            json={"error": {"message": "rate limited", "code": 429}},
        )

    with pytest.raises(ModelHTTPError):
        Agent(
            get_chat_model(
                openrouter_deployment(
                    request_settings=ModelRequestSettings(max_attempts=3)
                ),
                transport=httpx.MockTransport(handler),
                openrouter_retry_hooks=retry_hooks_for(
                    clock, jitter=lambda upper_bound: upper_bound
                ),
            ),
            output_type=str,
            defer_model_check=True,
        ).run_sync("Resolve it.")

    assert len(requests) == 3
    assert clock.sleeps == [0.0, 0.0]
