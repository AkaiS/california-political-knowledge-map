"""Shared OpenRouter admission behavior at the concurrent Agent seam."""

import asyncio
from dataclasses import dataclass, field

import httpx
from pydantic_ai import Agent

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
class CoordinatedClock:
    now_value: float = 1_700_000_000.0
    sleep_notifications: asyncio.Queue[float] = field(default_factory=asyncio.Queue)
    release_sleep: asyncio.Event = field(default_factory=asyncio.Event)

    def now(self) -> float:
        return self.now_value

    async def sleep(self, delay: float) -> None:
        await self.sleep_notifications.put(delay)
        await self.release_sleep.wait()
        self.now_value += delay


@dataclass
class AdvancingClock:
    now_value: float = 1_700_000_000.0
    sleep_notifications: asyncio.Queue[float] = field(default_factory=asyncio.Queue)
    _sleepers: list[tuple[float, asyncio.Event]] = field(default_factory=list)

    def now(self) -> float:
        return self.now_value

    async def sleep(self, delay: float) -> None:
        await self.sleep_notifications.put(delay)
        wake_at = self.now_value + delay
        wake_event = asyncio.Event()
        self._sleepers.append((wake_at, wake_event))
        await wake_event.wait()

    def advance(self, seconds: float) -> None:
        self.now_value += seconds
        for wake_at, wake_event in self._sleepers:
            if wake_at <= self.now_value:
                wake_event.set()


async def yield_until(predicate, *, limit: int = 10_000) -> None:
    for _ in range(limit):
        if predicate():
            return
        await asyncio.sleep(0)
    raise AssertionError("coordination condition was not reached")


def openrouter_deployment(model: str) -> ModelDeployment:
    return ModelDeployment(
        kind=DeploymentKind.OPENROUTER,
        model=model,
        request_settings=ModelRequestSettings(
            temperature=0.0,
            max_attempts=2,
        ),
        provider_policy=OpenRouterProviderPolicy(providers=("openai",)),
    )


def chat_completion(model: str) -> dict:
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


def test_a_429_blocks_a_later_request_across_openrouter_deployments(monkeypatch):
    asyncio.run(
        _test_a_429_blocks_a_later_request_across_openrouter_deployments(monkeypatch)
    )


async def _test_a_429_blocks_a_later_request_across_openrouter_deployments(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-openrouter-gate-test")
    clock = CoordinatedClock()
    hooks = OpenRouterRetryHooks(
        now=clock.now,
        sleep=clock.sleep,
        jitter=lambda upper_bound: upper_bound,
    )
    starts: list[str] = []
    later_request_started = asyncio.Event()
    attempts: dict[str, int] = {"openai/model-one": 0, "openai/model-two": 0}

    def handler_for(model: str):
        def handler(request: httpx.Request) -> httpx.Response:
            starts.append(model)
            if model == "openai/model-two":
                later_request_started.set()
            attempts[model] += 1
            if model == "openai/model-one" and attempts[model] == 1:
                return rate_limited_response(clock.now_value + 10)
            return httpx.Response(200, json=chat_completion(model))

        return handler

    first_agent = Agent(
        get_chat_model(
            openrouter_deployment("openai/model-one"),
            transport=httpx.MockTransport(handler_for("openai/model-one")),
            openrouter_retry_hooks=hooks,
        ),
        output_type=str,
        defer_model_check=True,
    )
    later_agent = Agent(
        get_chat_model(
            openrouter_deployment("openai/model-two"),
            transport=httpx.MockTransport(handler_for("openai/model-two")),
            openrouter_retry_hooks=hooks,
        ),
        output_type=str,
        defer_model_check=True,
    )

    first_task = asyncio.create_task(first_agent.run("first"))
    assert await clock.sleep_notifications.get() == 10.0
    later_task = asyncio.create_task(later_agent.run("later"))
    for _ in range(100):
        await asyncio.sleep(0)
    assert not later_request_started.is_set()
    assert starts == ["openai/model-one"]

    clock.release_sleep.set()
    first_result, later_result = await asyncio.gather(first_task, later_task)

    assert first_result.output == "resolved"
    assert later_result.output == "resolved"
    assert starts[0] == "openai/model-one"
    assert starts.count("openai/model-one") == 2
    assert starts.count("openai/model-two") == 1


def test_later_openrouter_rate_limit_deadline_extends_shared_pause(monkeypatch):
    asyncio.run(
        _test_later_openrouter_rate_limit_deadline_extends_shared_pause(monkeypatch)
    )


async def _test_later_openrouter_rate_limit_deadline_extends_shared_pause(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-openrouter-gate-test")
    clock = AdvancingClock()
    gate = OpenRouterAdmissionGate()
    hooks = OpenRouterRetryHooks(
        now=clock.now,
        sleep=clock.sleep,
        jitter=lambda upper_bound: upper_bound,
        admission_gate=gate,
    )
    base_time = clock.now_value
    starts: list[tuple[str, float]] = []
    attempts = {
        "openai/model-one": 0,
        "openai/model-two": 0,
        "openai/model-three": 0,
    }
    response_ready = {
        "openai/model-one": asyncio.Event(),
        "openai/model-two": asyncio.Event(),
    }

    def handler_for(model: str, reset_after: float | None = None):
        async def handler(request: httpx.Request) -> httpx.Response:
            del request
            starts.append((model, clock.now()))
            attempts[model] += 1
            if attempts[model] == 1 and reset_after is not None:
                await response_ready[model].wait()
                return rate_limited_response(base_time + reset_after)
            return httpx.Response(200, json=chat_completion(model))

        return handler

    first_agent = Agent(
        get_chat_model(
            openrouter_deployment("openai/model-one"),
            transport=httpx.MockTransport(handler_for("openai/model-one", 10)),
            openrouter_retry_hooks=hooks,
        ),
        output_type=str,
        defer_model_check=True,
    )
    second_agent = Agent(
        get_chat_model(
            openrouter_deployment("openai/model-two"),
            transport=httpx.MockTransport(handler_for("openai/model-two", 30)),
            openrouter_retry_hooks=hooks,
        ),
        output_type=str,
        defer_model_check=True,
    )
    third_agent = Agent(
        get_chat_model(
            openrouter_deployment("openai/model-three"),
            transport=httpx.MockTransport(handler_for("openai/model-three")),
            openrouter_retry_hooks=hooks,
        ),
        output_type=str,
        defer_model_check=True,
    )

    first_task = asyncio.create_task(first_agent.run("first"))
    second_task = asyncio.create_task(second_agent.run("second"))
    await yield_until(lambda: len(starts) == 2)
    response_ready["openai/model-one"].set()
    response_ready["openai/model-two"].set()
    waits = [
        await clock.sleep_notifications.get(),
        await clock.sleep_notifications.get(),
    ]
    assert sorted(waits) == [10.0, 30.0]

    third_task = asyncio.create_task(third_agent.run("third"))
    assert await clock.sleep_notifications.get() == 30.0
    assert [model for model, _ in starts] == [
        "openai/model-one",
        "openai/model-two",
    ]

    clock.advance(10)
    await yield_until(lambda: len(starts) == 3)
    assert [model for model, _ in starts] == [
        "openai/model-one",
        "openai/model-two",
        "openai/model-one",
    ]

    clock.advance(20)
    results = await asyncio.gather(first_task, second_task, third_task)

    assert [result.output for result in results] == ["resolved", "resolved", "resolved"]
    assert attempts == {
        "openai/model-one": 2,
        "openai/model-two": 2,
        "openai/model-three": 1,
    }
    starts_by_model = {
        model: [
            started_at for started_model, started_at in starts if started_model == model
        ]
        for model in attempts
    }
    assert starts_by_model == {
        "openai/model-one": [base_time, base_time + 10],
        "openai/model-two": [base_time, base_time + 30],
        "openai/model-three": [base_time + 30],
    }


def test_local_agent_bypasses_openrouter_admission_pause(monkeypatch):
    asyncio.run(_test_local_agent_bypasses_openrouter_admission_pause(monkeypatch))


async def _test_local_agent_bypasses_openrouter_admission_pause(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-openrouter-gate-test")
    clock = CoordinatedClock()
    gate = OpenRouterAdmissionGate()
    hooks = OpenRouterRetryHooks(
        now=clock.now,
        sleep=clock.sleep,
        jitter=lambda upper_bound: upper_bound,
        admission_gate=gate,
    )
    starts: list[str] = []
    openrouter_attempts = 0

    def openrouter_handler(request: httpx.Request) -> httpx.Response:
        nonlocal openrouter_attempts
        del request
        starts.append("openrouter")
        openrouter_attempts += 1
        if openrouter_attempts == 1:
            return rate_limited_response(clock.now_value + 10)
        return httpx.Response(200, json=chat_completion("openrouter"))

    def local_handler(request: httpx.Request) -> httpx.Response:
        del request
        starts.append("local")
        return httpx.Response(200, json=chat_completion("local"))

    openrouter_agent = Agent(
        get_chat_model(
            openrouter_deployment("openai/model-one"),
            transport=httpx.MockTransport(openrouter_handler),
            openrouter_retry_hooks=hooks,
        ),
        output_type=str,
        defer_model_check=True,
    )
    local_agent = Agent(
        get_chat_model(
            ModelDeployment(
                kind=DeploymentKind.LOCAL,
                model="google/gemma-4-26b-a4b-it-qat-q4_0",
                endpoint="http://local.test:9999",
                request_settings=ModelRequestSettings(
                    temperature=0.0,
                    max_attempts=1,
                ),
            ),
            transport=httpx.MockTransport(local_handler),
        ),
        output_type=str,
        defer_model_check=True,
    )

    openrouter_task = asyncio.create_task(openrouter_agent.run("remote"))
    assert await clock.sleep_notifications.get() == 10.0
    local_result = await local_agent.run("local")

    assert local_result.output == "resolved"
    assert starts == ["openrouter", "local"]

    clock.release_sleep.set()
    openrouter_result = await openrouter_task
    assert openrouter_result.output == "resolved"
    assert starts == ["openrouter", "local", "openrouter"]
