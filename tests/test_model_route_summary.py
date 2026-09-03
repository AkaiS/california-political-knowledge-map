"""Model Route Summaries at the completed Evaluation Run boundary."""

from __future__ import annotations

import asyncio
import json
import threading
from dataclasses import dataclass
from pathlib import Path

import httpx
from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelAPIError
from pydantic_evals.evaluators import Evaluator, EvaluatorContext

from knowledge_map.evaluation import (
    EvaluationCase,
    EvaluationGoldSet,
    run_gold_set,
    write_report,
)
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


class _PromptInput(BaseModel):
    prompt: str


@dataclass
class _ModelJudge(Evaluator):
    agent: Agent

    async def evaluate(self, ctx: EvaluatorContext) -> bool:
        return (await self.agent.run(f"Judge {ctx.output}")).output == "accepted"


def _gold_set(case_id: str = "case-route") -> EvaluationGoldSet:
    return EvaluationGoldSet(
        task="model-routes",
        description="Model route summary cases.",
        cases=(
            EvaluationCase(
                id=case_id,
                description="One model response",
                task_input=_PromptInput(prompt="Resolve this."),
            ),
        ),
    )


def _deployment() -> ModelDeployment:
    return ModelDeployment(
        kind=DeploymentKind.OPENROUTER,
        model="requested/model",
        provider_policy=OpenRouterProviderPolicy(providers=("configured-provider",)),
    )


def _completion(
    *, response_model: str = "effective/model", provider: str | None = "observed/provider"
) -> dict:
    response = {
        "id": "route-response",
        "object": "chat.completion",
        "created": 0,
        "model": response_model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "resolved"},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},
    }
    if provider is not None:
        response["provider"] = provider
    return response


def test_completed_report_serializes_one_observed_model_route(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-model-route-test")
    deployment = _deployment()
    model = get_chat_model(
        deployment,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=_completion())
        ),
    )
    agent = Agent(model, output_type=str, defer_model_check=True)
    report = run_gold_set(
        _gold_set(),
        task=lambda case_input: agent.run_sync(case_input.prompt).output,
        evaluators=(),
    )

    assert report.cases[0].attributes["model_routes"] == [
        {
            "response_model": "effective/model",
            "downstream_provider": "observed/provider",
            "request_count": 1,
        }
    ]

    path = write_report(
        report,
        task="model-routes",
        deployment=deployment,
        gold_set_path=tmp_path / "gold.yaml",
        root=tmp_path / "reports",
    )
    document = json.loads(path.read_text())
    assert document["report"]["cases"][0]["attributes"]["model_routes"] == [
        {
            "response_model": "effective/model",
            "downstream_provider": "observed/provider",
            "request_count": 1,
        }
    ]


def test_successful_case_without_a_model_response_has_no_routes() -> None:
    report = run_gold_set(
        _gold_set("case-without-response"),
        task=lambda case_input: case_input.prompt,
        evaluators=(),
    )

    assert not report.failures
    assert report.cases[0].attributes["model_routes"] == []


def test_repeated_and_mixed_routes_are_grouped_in_stable_order(monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-model-route-grouping")
    deployment = _deployment()
    responses = iter(
        (
            _completion(response_model="z/model", provider="provider-b"),
            _completion(response_model="a/model", provider="provider-a"),
            _completion(response_model="z/model", provider="provider-b"),
        )
    )
    model = get_chat_model(
        deployment,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=next(responses))
        ),
    )
    agent = Agent(model, output_type=str, defer_model_check=True)

    def task(case_input: _PromptInput) -> str:
        outputs = [agent.run_sync(case_input.prompt).output for _ in range(3)]
        return " ".join(outputs)

    report = run_gold_set(_gold_set("case-grouped"), task=task, evaluators=())

    assert report.cases[0].attributes["model_routes"] == [
        {
            "response_model": "a/model",
            "downstream_provider": "provider-a",
            "request_count": 1,
        },
        {
            "response_model": "z/model",
            "downstream_provider": "provider-b",
            "request_count": 2,
        },
    ]


def test_missing_response_model_uses_pydantic_ai_fallback(monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-model-route-fallback")
    deployment = _deployment()
    agent = Agent(
        get_chat_model(
            deployment,
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    json=_completion(response_model="", provider="observed/provider"),
                )
            ),
        ),
        output_type=str,
        defer_model_check=True,
    )

    report = run_gold_set(
        _gold_set("case-model-fallback"),
        task=lambda case_input: agent.run_sync(case_input.prompt).output,
        evaluators=(),
    )

    assert report.cases[0].attributes["model_routes"] == [
        {
            "response_model": "requested/model",
            "downstream_provider": "observed/provider",
            "request_count": 1,
        }
    ]


def test_missing_openrouter_provider_is_not_inferred_from_configuration(
    monkeypatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-model-route-no-provider")
    deployment = _deployment()
    agent = Agent(
        get_chat_model(
            deployment,
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200, json=_completion(provider=None)
                )
            ),
        ),
        output_type=str,
        defer_model_check=True,
    )

    report = run_gold_set(
        _gold_set("case-no-provider"),
        task=lambda case_input: agent.run_sync(case_input.prompt).output,
        evaluators=(),
    )

    assert report.cases[0].attributes["model_routes"] == [
        {
            "response_model": "effective/model",
            "downstream_provider": None,
            "request_count": 1,
        }
    ]


def test_local_response_has_no_downstream_provider() -> None:
    deployment = ModelDeployment(
        kind=DeploymentKind.LOCAL,
        model="local/requested-model",
        endpoint="http://llama.test/v1",
        request_settings=ModelRequestSettings(max_attempts=1),
    )
    agent = Agent(
        get_chat_model(
            deployment,
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    json=_completion(
                        response_model="local/effective-model",
                        provider="payload/provider-must-not-leak",
                    ),
                )
            ),
        ),
        output_type=str,
        defer_model_check=True,
    )

    report = run_gold_set(
        _gold_set("case-local"),
        task=lambda case_input: agent.run_sync(case_input.prompt).output,
        evaluators=(),
    )

    assert report.cases[0].attributes["model_routes"] == [
        {
            "response_model": "local/effective-model",
            "downstream_provider": None,
            "request_count": 1,
        }
    ]


def test_evaluator_model_request_is_excluded_but_its_result_remains(
    monkeypatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-model-route-evaluator")
    deployment = _deployment()
    task_agent = Agent(
        get_chat_model(
            deployment,
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    json=_completion(
                        response_model="task/model", provider="task/provider"
                    ),
                )
            ),
        ),
        output_type=str,
        defer_model_check=True,
    )
    judge_agent = Agent(
        get_chat_model(
            deployment,
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    json={
                        **_completion(
                            response_model="judge/model", provider="judge/provider"
                        ),
                        "choices": [
                            {
                                "index": 0,
                                "message": {
                                    "role": "assistant",
                                    "content": "accepted",
                                },
                                "finish_reason": "stop",
                            }
                        ],
                    },
                )
            ),
        ),
        output_type=str,
        defer_model_check=True,
    )

    report = run_gold_set(
        _gold_set("case-evaluator"),
        task=lambda case_input: task_agent.run_sync(case_input.prompt).output,
        evaluators=(_ModelJudge(agent=judge_agent),),
    )

    assert report.cases[0].attributes["model_routes"] == [
        {
            "response_model": "task/model",
            "downstream_provider": "task/provider",
            "request_count": 1,
        }
    ]
    assert report.cases[0].assertions["_ModelJudge"].value is True


def test_concurrent_cases_receive_only_their_own_route(monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-model-route-concurrency")
    deployment = _deployment()
    gold_set = EvaluationGoldSet(
        task="model-routes",
        description="Concurrent route cases.",
        cases=(
            EvaluationCase(
                id="case-alpha",
                description="Alpha route",
                task_input=_PromptInput(prompt="Run alpha."),
            ),
            EvaluationCase(
                id="case-beta",
                description="Beta route",
                task_input=_PromptInput(prompt="Run beta."),
            ),
        ),
    )
    started = threading.Barrier(2)

    async def handler(request: httpx.Request) -> httpx.Response:
        prompt = request.content.decode()
        route = "alpha" if "Run alpha" in prompt else "beta"
        try:
            await asyncio.to_thread(started.wait, 5)
        except threading.BrokenBarrierError as error:
            raise AssertionError("the Evaluation Cases did not overlap") from error
        return httpx.Response(
            200,
            json=_completion(
                response_model=f"{route}/model", provider=f"{route}/provider"
            ),
        )

    agent = Agent(
        get_chat_model(
            deployment,
            transport=httpx.MockTransport(handler),
            openrouter_retry_hooks=OpenRouterRetryHooks(
                admission_gate=OpenRouterAdmissionGate(max_concurrency=2)
            ),
        ),
        output_type=str,
        defer_model_check=True,
    )

    report = run_gold_set(
        gold_set,
        task=lambda case_input: agent.run_sync(case_input.prompt).output,
        evaluators=(),
        max_concurrency=2,
    )

    assert {
        case.name: case.attributes["model_routes"] for case in report.cases
    } == {
        "case-alpha": [
            {
                "response_model": "alpha/model",
                "downstream_provider": "alpha/provider",
                "request_count": 1,
            }
        ],
        "case-beta": [
            {
                "response_model": "beta/model",
                "downstream_provider": "beta/provider",
                "request_count": 1,
            }
        ],
    }


def test_request_without_a_response_does_not_contribute_a_route() -> None:
    deployment = ModelDeployment(
        kind=DeploymentKind.LOCAL,
        model="local/requested-model",
        endpoint="http://llama.test/v1",
        request_settings=ModelRequestSettings(max_attempts=1),
    )
    agent = Agent(
        get_chat_model(
            deployment,
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    500, json={"error": {"message": "unavailable"}}
                )
            ),
        ),
        output_type=str,
        defer_model_check=True,
    )

    def task(case_input: _PromptInput) -> str:
        try:
            return agent.run_sync(case_input.prompt).output
        except ModelAPIError:
            return "task fallback"

    report = run_gold_set(
        _gold_set("case-request-without-response"), task=task, evaluators=()
    )

    assert not report.failures
    assert report.cases[0].attributes["model_routes"] == []


def test_serialized_route_summary_preserves_metrics_and_run_provenance(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-model-route-report")
    deployment = ModelDeployment(
        kind=DeploymentKind.OPENROUTER,
        model="openai/gpt-4o-mini",
        provider_policy=OpenRouterProviderPolicy(providers=("openai",)),
    )
    agent = Agent(
        get_chat_model(
            deployment,
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    json=_completion(
                        response_model="openai/gpt-4o-mini",
                        provider="openai/hosted",
                    ),
                )
            ),
        ),
        output_type=str,
        defer_model_check=True,
    )
    report = run_gold_set(
        _gold_set("case-complete-report"),
        task=lambda case_input: agent.run_sync(case_input.prompt).output,
        evaluators=(),
    )
    gold_set_path = tmp_path / "gold.yaml"

    path = write_report(
        report,
        task="model-routes",
        deployment=deployment,
        gold_set_path=gold_set_path,
        split="held-out",
        root=tmp_path / "reports",
    )
    document = json.loads(path.read_text())
    serialized_case = document["report"]["cases"][0]

    assert serialized_case["metrics"]["requests"] == 1
    assert serialized_case["metrics"]["input_tokens"] == 2
    assert serialized_case["metrics"]["output_tokens"] == 3
    assert serialized_case["metrics"]["cost"] > 0
    assert serialized_case["attributes"]["request_provenance"]
    assert document["task"] == "model-routes"
    assert document["model"] == deployment.model
    assert document["deployment"] == deployment.model_dump(mode="json")
    assert document["commit"]
    assert isinstance(document["dirty"], bool)
    assert document["gold_set"] == str(gold_set_path)
    assert document["split"] == "held-out"
