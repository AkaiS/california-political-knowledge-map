"""Single-probe OpenRouter resumption at the concurrent Agent seam."""

import asyncio
from dataclasses import dataclass, field

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
from knowledge_map.utils.models import (
    OpenRouterAdmissionGate,
    OpenRouterRetryHooks,
    get_chat_model,
)


@dataclass
class ControlledClock:
    now_value: float = 1_700_000_000.0
    sleep_notifications: asyncio.Queue[float] = field(default_factory=asyncio.Queue)
    _sleepers: list[tuple[float, asyncio.Event]] = field(default_factory=list)

    def now(self) -> float:
        return self.now_value

    async def sleep(self, delay: float) -> None:
        await self.sleep_notifications.put(delay)
        wake_event = asyncio.Event()
        self._sleepers.append((self.now_value + delay, wake_event))
        await wake_event.wait()

    def advance(self, seconds: float) -> None:
        self.now_value += seconds
        for wake_at, wake_event in self._sleepers:
            if wake_at <= self.now_value:
                wake_event.set()


def deployment(model: str, *, max_attempts: int = 1) -> ModelDeployment:
    return ModelDeployment(
        kind=DeploymentKind.OPENROUTER,
        model=model,
        request_settings=ModelRequestSettings(
            temperature=0.0,
            max_attempts=max_attempts,
        ),
        provider_policy=OpenRouterProviderPolicy(providers=("openai",)),
    )


def completion(model: str) -> dict:
    return {
        "id": f"chatcmpl-{model}",
        "object": "chat.completion",
        "created": 0,
        "model": model,
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


def rate_limited_response(reset_at: float) -> httpx.Response:
    return httpx.Response(
        429,
        headers={"X-RateLimit-Reset": str(reset_at)},
        json={"error": {"message": "rate limited", "code": 429}},
    )


def test_pause_expiry_admits_exactly_one_probe(monkeypatch):
    asyncio.run(_test_pause_expiry_admits_exactly_one_probe(monkeypatch))


async def _test_pause_expiry_admits_exactly_one_probe(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-openrouter-probe-test")
    clock = ControlledClock()
    gate = OpenRouterAdmissionGate()
    hooks = OpenRouterRetryHooks(
        now=clock.now,
        sleep=clock.sleep,
        jitter=lambda upper_bound: upper_bound,
        admission_gate=gate,
    )

    async def seed_handler(request: httpx.Request) -> httpx.Response:
        del request
        return rate_limited_response(clock.now_value + 10)

    with pytest.raises(ModelHTTPError) as seed_error:
        await Agent(
            get_chat_model(
                deployment("openai/seed"),
                transport=httpx.MockTransport(seed_handler),
                openrouter_retry_hooks=hooks,
            ),
            output_type=str,
            defer_model_check=True,
        ).run("seed")
    assert seed_error.value.status_code == 429

    waiting_starts: list[str] = []
    probe_started = asyncio.Event()
    release_probe = asyncio.Event()

    def waiting_handler_for(model: str):
        async def handler(request: httpx.Request) -> httpx.Response:
            del request
            waiting_starts.append(model)
            if len(waiting_starts) == 1:
                probe_started.set()
                await release_probe.wait()
            return httpx.Response(200, json=completion(model))

        return handler

    agents = [
        Agent(
            get_chat_model(
                deployment(f"openai/wait-{index}"),
                transport=httpx.MockTransport(
                    waiting_handler_for(f"openai/wait-{index}")
                ),
                openrouter_retry_hooks=hooks,
            ),
            output_type=str,
            defer_model_check=True,
        )
        for index in range(3)
    ]
    tasks = [
        asyncio.create_task(agent.run(f"wait-{index}"))
        for index, agent in enumerate(agents)
    ]

    assert [await clock.sleep_notifications.get() for _ in range(3)] == [
        10.0,
        10.0,
        10.0,
    ]
    clock.advance(10)
    await probe_started.wait()
    for _ in range(100):
        await asyncio.sleep(0)
    assert len(waiting_starts) == 1

    release_probe.set()
    results = await asyncio.gather(*tasks)
    assert [result.output for result in results] == ["resolved"] * 3
    assert len(waiting_starts) == 3


def test_probe_429_recloses_without_releasing_waiting_burst(monkeypatch):
    asyncio.run(_test_probe_429_recloses_without_releasing_waiting_burst(monkeypatch))


async def _test_probe_429_recloses_without_releasing_waiting_burst(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-openrouter-probe-test")
    clock = ControlledClock()
    base_time = clock.now_value
    gate = OpenRouterAdmissionGate()
    hooks = OpenRouterRetryHooks(
        now=clock.now,
        sleep=clock.sleep,
        jitter=lambda upper_bound: upper_bound,
        admission_gate=gate,
    )

    async def seed_handler(request: httpx.Request) -> httpx.Response:
        del request
        return rate_limited_response(base_time + 10)

    with pytest.raises(ModelHTTPError):
        await Agent(
            get_chat_model(
                deployment("openai/seed"),
                transport=httpx.MockTransport(seed_handler),
                openrouter_retry_hooks=hooks,
            ),
            output_type=str,
            defer_model_check=True,
        ).run("seed")

    waiting_starts: list[float] = []
    first_probe_started = asyncio.Event()
    first_probe_failed = asyncio.Event()
    second_probe_started = asyncio.Event()
    release_second_probe = asyncio.Event()

    def waiting_handler_for(model: str):
        async def handler(request: httpx.Request) -> httpx.Response:
            del request
            waiting_starts.append(clock.now())
            if len(waiting_starts) == 1:
                first_probe_started.set()
                return rate_limited_response(base_time + 20)
            if len(waiting_starts) == 2:
                second_probe_started.set()
                await release_second_probe.wait()
            return httpx.Response(200, json=completion(model))

        return handler

    agents = [
        Agent(
            get_chat_model(
                deployment(f"openai/wait-{index}"),
                transport=httpx.MockTransport(
                    waiting_handler_for(f"openai/wait-{index}")
                ),
                openrouter_retry_hooks=hooks,
            ),
            output_type=str,
            defer_model_check=True,
        )
        for index in range(3)
    ]

    async def capture_probe_result(agent: Agent, index: int):
        try:
            return await agent.run(f"wait-{index}")
        except ModelHTTPError as error:
            first_probe_failed.set()
            return error

    tasks = [
        asyncio.create_task(capture_probe_result(agent, index))
        for index, agent in enumerate(agents)
    ]

    assert [await clock.sleep_notifications.get() for _ in range(3)] == [
        10.0,
        10.0,
        10.0,
    ]
    clock.advance(10)
    await first_probe_started.wait()
    await first_probe_failed.wait()
    assert waiting_starts == [base_time + 10]

    assert [await clock.sleep_notifications.get() for _ in range(2)] == [
        10.0,
        10.0,
    ]
    clock.advance(10)
    await second_probe_started.wait()
    for _ in range(100):
        await asyncio.sleep(0)
    assert waiting_starts == [base_time + 10, base_time + 20]

    release_second_probe.set()
    results = await asyncio.gather(*tasks)
    errors = [result for result in results if isinstance(result, ModelHTTPError)]
    successful_results = [result for result in results if not isinstance(result, ModelHTTPError)]
    assert len(errors) == 1
    assert errors[0].status_code == 429
    assert [result.output for result in successful_results] == ["resolved"] * 2
    assert waiting_starts == [base_time + 10, base_time + 20, base_time + 20]


def test_interrupted_probe_keeps_waiting_callers_held(monkeypatch):
    asyncio.run(_test_interrupted_probe_keeps_waiting_callers_held(monkeypatch))


async def _test_interrupted_probe_keeps_waiting_callers_held(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-openrouter-probe-test")
    clock = ControlledClock()
    base_time = clock.now_value
    gate = OpenRouterAdmissionGate()
    hooks = OpenRouterRetryHooks(
        now=clock.now,
        sleep=clock.sleep,
        jitter=lambda upper_bound: upper_bound,
        admission_gate=gate,
    )

    async def seed_handler(request: httpx.Request) -> httpx.Response:
        del request
        return rate_limited_response(base_time + 10)

    with pytest.raises(ModelHTTPError):
        await Agent(
            get_chat_model(
                deployment("openai/seed"),
                transport=httpx.MockTransport(seed_handler),
                openrouter_retry_hooks=hooks,
            ),
            output_type=str,
            defer_model_check=True,
        ).run("seed")

    waiting_starts: list[str] = []
    first_probe_started = asyncio.Event()
    second_probe_started = asyncio.Event()
    release_second_probe = asyncio.Event()

    def waiting_handler_for(model: str):
        async def handler(request: httpx.Request) -> httpx.Response:
            del request
            waiting_starts.append(model)
            if len(waiting_starts) == 1:
                first_probe_started.set()
                raise httpx.ConnectError("probe connection reset")
            if len(waiting_starts) == 2:
                second_probe_started.set()
                await release_second_probe.wait()
            return httpx.Response(200, json=completion(model))

        return handler

    agents = [
        Agent(
            get_chat_model(
                deployment(f"openai/wait-{index}"),
                transport=httpx.MockTransport(
                    waiting_handler_for(f"openai/wait-{index}")
                ),
                openrouter_retry_hooks=hooks,
            ),
            output_type=str,
            defer_model_check=True,
        )
        for index in range(3)
    ]

    async def capture_result(agent: Agent, index: int):
        try:
            return await agent.run(f"wait-{index}")
        except ModelAPIError as error:
            return error

    tasks = [
        asyncio.create_task(capture_result(agent, index))
        for index, agent in enumerate(agents)
    ]

    assert [await clock.sleep_notifications.get() for _ in range(3)] == [
        10.0,
        10.0,
        10.0,
    ]
    clock.advance(10)
    await first_probe_started.wait()
    first_result = await tasks[0]
    assert isinstance(first_result, ModelAPIError)
    await second_probe_started.wait()
    for _ in range(100):
        await asyncio.sleep(0)
    assert waiting_starts == ["openai/wait-0", "openai/wait-1"]

    release_second_probe.set()
    results = await asyncio.gather(*tasks)
    assert not isinstance(results[1], BaseException)
    assert not isinstance(results[2], BaseException)
    assert results[1].output == "resolved"
    assert results[2].output == "resolved"
