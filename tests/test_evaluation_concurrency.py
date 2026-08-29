"""Evaluation concurrency reaches both case execution and OpenRouter admission."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from types import SimpleNamespace

import httpx
from pydantic_ai import Agent

from knowledge_map.cli import evaluate
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
    openrouter_admission_ceiling,
)


class _RecordingCeiling:
    def __init__(self, ceiling: int, events: list[tuple[str, int]]) -> None:
        self.ceiling = ceiling
        self.events = events

    def __enter__(self):
        self.events.append(("enter", self.ceiling))
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.events.append(("exit", self.ceiling))
        return False


def test_openrouter_evaluation_uses_one_case_and_admission_ceiling(
    tmp_path: Path, monkeypatch
) -> None:
    gold_set_path = tmp_path / "relevance.yaml"
    gold_set_path.write_text("placeholder")
    calls: dict[str, object] = {}
    events: list[tuple[str, int]] = []

    def build(deployment: ModelDeployment, gold_set: object):
        calls["deployment"] = deployment
        return lambda case_input: {"classification": "RELEVANT"}

    task = SimpleNamespace(
        name="relevance",
        gold_set_stem="relevance",
        input_type=dict,
        output_type=dict,
        metadata_type=dict,
        default_model="local/model",
        build=build,
        evaluators=(),
    )
    report = SimpleNamespace(print=lambda **kwargs: None)

    monkeypatch.setattr(evaluate, "task_named", lambda name: task)
    monkeypatch.setattr(evaluate, "load_gold_set", lambda *args, **kwargs: object())
    monkeypatch.setattr(
        evaluate,
        "run_gold_set",
        lambda *args, **kwargs: calls.update(run_kwargs=kwargs) or report,
    )
    monkeypatch.setattr(
        evaluate,
        "openrouter_admission_ceiling",
        lambda ceiling: _RecordingCeiling(ceiling, events),
        raising=False,
    )
    monkeypatch.setattr(
        evaluate,
        "write_report",
        lambda *args, **kwargs: tmp_path / "report.json",
    )
    monkeypatch.setattr(evaluate, "load_dotenv", lambda: None)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-evaluation-test")
    monkeypatch.setenv("OPENROUTER_MODEL", "configured/model")
    monkeypatch.setenv("OPENROUTER_PROVIDERS", "google-ai-studio")

    evaluate.dispatch(
        argparse.Namespace(
            eval_action="run",
            task="relevance",
            gold_set=gold_set_path,
            deployment="openrouter",
            model=None,
            split=None,
            max_concurrency=4,
            no_report=False,
        )
    )

    assert calls["run_kwargs"]["max_concurrency"] == 4
    assert events == [("enter", 4), ("exit", 4)]


def _openrouter_deployment(model: str) -> ModelDeployment:
    return ModelDeployment(
        kind=DeploymentKind.OPENROUTER,
        model=model,
        request_settings=ModelRequestSettings(max_attempts=1),
        provider_policy=OpenRouterProviderPolicy(providers=("openai",)),
    )


def _completion(model: str) -> dict[str, object]:
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


def test_sequential_openrouter_runs_do_not_leak_the_previous_ceiling(monkeypatch) -> None:
    asyncio.run(_test_sequential_openrouter_runs_do_not_leak_the_previous_ceiling(monkeypatch))


async def _test_sequential_openrouter_runs_do_not_leak_the_previous_ceiling(
    monkeypatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-evaluation-test")

    async def run_batch(ceiling: int, prefix: str) -> None:
        starts: list[str] = []
        enough_started = asyncio.Event()
        release = asyncio.Event()

        def handler_for(model: str):
            async def handler(request: httpx.Request) -> httpx.Response:
                del request
                starts.append(model)
                if len(starts) == ceiling:
                    enough_started.set()
                await release.wait()
                return httpx.Response(200, json=_completion(model))

            return handler

        agents = [
            Agent(
                get_chat_model(
                    _openrouter_deployment(f"openai/{prefix}-{index}"),
                    transport=httpx.MockTransport(handler_for(f"{prefix}-{index}")),
                ),
                name=f"evaluation_ceiling_{prefix}_{index}",
                output_type=str,
                defer_model_check=True,
            )
            for index in range(3)
        ]
        tasks = [asyncio.create_task(agent.run(f"case-{index}")) for index, agent in enumerate(agents)]
        await enough_started.wait()
        for _ in range(20):
            await asyncio.sleep(0)
        assert len(starts) == ceiling
        release.set()
        results = await asyncio.gather(*tasks)
        assert [result.output for result in results] == ["resolved"] * 3

    with openrouter_admission_ceiling(2):
        await run_batch(2, "first")

    with openrouter_admission_ceiling(3):
        await run_batch(3, "second")


def test_expired_pause_does_not_admit_probe_above_ceiling() -> None:
    asyncio.run(_test_expired_pause_does_not_admit_probe_above_ceiling())


async def _test_expired_pause_does_not_admit_probe_above_ceiling() -> None:
    gate = OpenRouterAdmissionGate()
    hooks = OpenRouterRetryHooks(now=lambda: 1.0, sleep=asyncio.sleep)

    with gate.configured_ceiling(2):
        assert await gate.wait_until_open(hooks) is False
        assert await gate.wait_until_open(hooks) is False
        gate.pause_until(0.0)

        probe_task = asyncio.create_task(gate.wait_until_open(hooks))
        await asyncio.sleep(0)
        assert not probe_task.done()

        gate.request_completed(is_probe=False, now=1.0)
        assert await probe_task is True
        gate.request_completed(is_probe=False, now=1.0)
        gate.request_completed(is_probe=True, now=1.0)
