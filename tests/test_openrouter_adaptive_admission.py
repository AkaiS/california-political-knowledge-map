"""Adaptive OpenRouter admission at the concurrent Agent seam."""

import asyncio
from dataclasses import dataclass, field

import httpx
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


async def yield_until(predicate, *, limit: int = 10_000) -> None:
    for _ in range(limit):
        if predicate():
            return
        await asyncio.sleep(0)
    raise AssertionError("coordination condition was not reached")


def deployment(model: str) -> ModelDeployment:
    return ModelDeployment(
        kind=DeploymentKind.OPENROUTER,
        model=model,
        request_settings=ModelRequestSettings(
            temperature=0.0,
            max_attempts=1,
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


def test_successes_restore_admission_gradually_at_the_ceiling(monkeypatch):
    asyncio.run(_test_successes_restore_admission_gradually_at_the_ceiling(monkeypatch))


async def _test_successes_restore_admission_gradually_at_the_ceiling(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-openrouter-adaptive-test")
    clock = ControlledClock()
    base_time = clock.now_value
    gate = OpenRouterAdmissionGate(max_concurrency=3)
    hooks = OpenRouterRetryHooks(
        now=clock.now,
        sleep=clock.sleep,
        jitter=lambda upper_bound: upper_bound,
        admission_gate=gate,
    )

    seed_started = 0
    all_seeds_started = asyncio.Event()
    release_seed_responses = asyncio.Event()

    async def seed_handler(request: httpx.Request) -> httpx.Response:
        nonlocal seed_started
        del request
        seed_started += 1
        if seed_started == 2:
            all_seeds_started.set()
        await all_seeds_started.wait()
        await release_seed_responses.wait()
        return rate_limited_response(base_time + 10)

    seed_agents = [
        Agent(
            get_chat_model(
                deployment(f"openai/seed-{index}"),
                transport=httpx.MockTransport(seed_handler),
                openrouter_retry_hooks=hooks,
            ),
            name=f"adaptive_seed_{index}",
            output_type=str,
            defer_model_check=True,
        )
        for index in range(2)
    ]

    async def capture_seed_error(agent: Agent, index: int):
        try:
            return await agent.run(f"seed-{index}")
        except ModelHTTPError as error:
            return error

    seed_tasks = [
        asyncio.create_task(capture_seed_error(agent, index))
        for index, agent in enumerate(seed_agents)
    ]
    await all_seeds_started.wait()
    release_seed_responses.set()
    seed_results = await asyncio.gather(*seed_tasks)
    assert [result.status_code for result in seed_results] == [429, 429]

    waiting_starts: list[str] = []
    probe_started = asyncio.Event()
    release_probe = asyncio.Event()
    release_followers = [asyncio.Event() for _ in range(5)]

    def waiting_handler_for(model: str):
        async def handler(request: httpx.Request) -> httpx.Response:
            del request
            waiting_starts.append(model)
            start_number = len(waiting_starts)
            if start_number == 1:
                probe_started.set()
                await release_probe.wait()
            else:
                await release_followers[start_number - 2].wait()
            return httpx.Response(200, json=completion(model))

        return handler

    waiting_agents = [
        Agent(
            get_chat_model(
                deployment(f"openai/wait-{index}"),
                transport=httpx.MockTransport(
                    waiting_handler_for(f"openai/wait-{index}")
                ),
                openrouter_retry_hooks=hooks,
            ),
            name=f"adaptive_wait_{index}",
            output_type=str,
            defer_model_check=True,
        )
        for index in range(6)
    ]
    waiting_tasks = [
        asyncio.create_task(agent.run(f"wait-{index}"))
        for index, agent in enumerate(waiting_agents)
    ]

    assert [await clock.sleep_notifications.get() for _ in range(6)] == [
        10.0,
        10.0,
        10.0,
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
    await yield_until(lambda: len(waiting_starts) >= 3)
    for _ in range(100):
        await asyncio.sleep(0)
    assert len(waiting_starts) == 3

    release_followers[0].set()
    await yield_until(lambda: len(waiting_starts) >= 5)
    for _ in range(100):
        await asyncio.sleep(0)
    assert len(waiting_starts) == 5

    release_followers[1].set()
    await yield_until(lambda: len(waiting_starts) >= 6)
    for _ in range(100):
        await asyncio.sleep(0)
    assert len(waiting_starts) == 6

    release_followers[2].set()
    release_followers[3].set()
    release_followers[4].set()
    results = await asyncio.gather(*waiting_tasks)
    assert [result.output for result in results] == ["resolved"] * 6
