"""Model Route Summaries at the completed Evaluation Run boundary."""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

import httpx
from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelAPIError
from pydantic_evals.evaluators import Evaluator, EvaluatorContext

import knowledge_map.adapters.coreference as coreference_adapter_module
import knowledge_map.evaluation.tasks.coreference as coreference_task_module
from knowledge_map.evaluation import (
    EvaluationCase,
    EvaluationDataSet,
    run_data_set,
    write_report,
)
from knowledge_map.evaluation.tasks.coreference import (
    CoreferenceInput,
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


class _ModelRoutePromptInput(BaseModel):
    prompt: str


@dataclass
class _ModelOutputAcceptanceEvaluator(Evaluator):
    agent: Agent

    async def evaluate(self, ctx: EvaluatorContext) -> bool:
        return (await self.agent.run(f"Judge {ctx.output}")).output == "accepted"


def _build_model_route_data_set(case_id: str = "case-route") -> EvaluationDataSet:
    return EvaluationDataSet(
        task="model-routes",
        description="Model route summary cases.",
        cases=(
            EvaluationCase(
                id=case_id,
                description="One model response",
                task_input=_ModelRoutePromptInput(prompt="Resolve this."),
            ),
        ),
    )


def _build_openrouter_model_route_deployment() -> ModelDeployment:
    return ModelDeployment(
        kind=DeploymentKind.OPENROUTER,
        model="requested/model",
        provider_policy=OpenRouterProviderPolicy(providers=("configured-provider",)),
    )


def _build_chat_completion_payload(
    *,
    response_model: str = "effective/model",
    provider: str | None = "observed/provider",
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


def _build_structured_chat_completion_payload(
    *, response_model: str, provider: str, payload: object
) -> dict:
    """Build the JSON envelope used by structured Coreference agents."""

    response = _build_chat_completion_payload(
        response_model=response_model,
        provider=provider,
    )
    response["choices"][0]["message"]["content"] = json.dumps(
        {"response": payload}
    )
    return response


def _build_local_model_route_deployment() -> ModelDeployment:
    return ModelDeployment(
        kind=DeploymentKind.LOCAL,
        model="local/requested-model",
        endpoint="http://llama.test/v1",
        request_settings=ModelRequestSettings(max_attempts=1),
    )


def _build_chat_agent_with_mock_transport(
    deployment: ModelDeployment,
    handler: Callable[[httpx.Request], httpx.Response | Awaitable[httpx.Response]],
    *,
    openrouter_retry_hooks: OpenRouterRetryHooks | None = None,
) -> Agent:
    return Agent(
        get_chat_model(
            deployment,
            transport=httpx.MockTransport(handler),
            openrouter_retry_hooks=openrouter_retry_hooks,
        ),
        output_type=str,
        defer_model_check=True,
    )


def test_completed_report_serializes_one_observed_model_route(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-model-route-test")
    deployment = _build_openrouter_model_route_deployment()
    agent = _build_chat_agent_with_mock_transport(
        deployment,
        lambda request: httpx.Response(200, json=_build_chat_completion_payload()),
    )
    report = run_data_set(
        _build_model_route_data_set(),
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
        data_set_path=tmp_path / "relevance.yaml",
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
    report = run_data_set(
        _build_model_route_data_set("case-without-response"),
        task=lambda case_input: case_input.prompt,
        evaluators=(),
    )

    assert not report.failures
    assert report.cases[0].attributes["model_routes"] == []


def test_repeated_and_mixed_routes_are_grouped_in_stable_order(monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-model-route-grouping")
    deployment = _build_openrouter_model_route_deployment()
    responses = iter(
        (
            _build_chat_completion_payload(
                response_model="z/model", provider="provider-b"
            ),
            _build_chat_completion_payload(
                response_model="a/model", provider="provider-a"
            ),
            _build_chat_completion_payload(
                response_model="z/model", provider="provider-b"
            ),
        )
    )
    agent = _build_chat_agent_with_mock_transport(
        deployment,
        lambda request: httpx.Response(200, json=next(responses)),
    )

    def task(case_input: _ModelRoutePromptInput) -> str:
        outputs = [agent.run_sync(case_input.prompt).output for _ in range(3)]
        return " ".join(outputs)

    report = run_data_set(
        _build_model_route_data_set("case-grouped"), task=task, evaluators=()
    )

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
    deployment = _build_openrouter_model_route_deployment()
    agent = _build_chat_agent_with_mock_transport(
        deployment,
        lambda request: httpx.Response(
            200,
            json=_build_chat_completion_payload(
                response_model="", provider="observed/provider"
            ),
        ),
    )

    report = run_data_set(
        _build_model_route_data_set("case-model-fallback"),
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
    deployment = _build_openrouter_model_route_deployment()
    agent = _build_chat_agent_with_mock_transport(
        deployment,
        lambda request: httpx.Response(
            200, json=_build_chat_completion_payload(provider=None)
        ),
    )

    report = run_data_set(
        _build_model_route_data_set("case-no-provider"),
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
    deployment = _build_local_model_route_deployment()
    agent = _build_chat_agent_with_mock_transport(
        deployment,
        lambda request: httpx.Response(
            200,
            json=_build_chat_completion_payload(
                response_model="local/effective-model",
                provider="payload/provider-must-not-leak",
            ),
        ),
    )

    report = run_data_set(
        _build_model_route_data_set("case-local"),
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
    deployment = _build_openrouter_model_route_deployment()
    task_agent = _build_chat_agent_with_mock_transport(
        deployment,
        lambda request: httpx.Response(
            200,
            json=_build_chat_completion_payload(
                response_model="task/model", provider="task/provider"
            ),
        ),
    )
    judge_agent = _build_chat_agent_with_mock_transport(
        deployment,
        lambda request: httpx.Response(
            200,
            json={
                **_build_chat_completion_payload(
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
        ),
    )

    report = run_data_set(
        _build_model_route_data_set("case-evaluator"),
        task=lambda case_input: task_agent.run_sync(case_input.prompt).output,
        evaluators=(_ModelOutputAcceptanceEvaluator(agent=judge_agent),),
    )

    assert report.cases[0].attributes["model_routes"] == [
        {
            "response_model": "task/model",
            "downstream_provider": "task/provider",
            "request_count": 1,
        }
    ]
    assert report.cases[0].assertions["_ModelOutputAcceptanceEvaluator"].value is True


def test_concurrent_cases_receive_only_their_own_route(monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-model-route-concurrency")
    deployment = _build_openrouter_model_route_deployment()
    data_set = EvaluationDataSet(
        task="model-routes",
        description="Concurrent route cases.",
        cases=(
            EvaluationCase(
                id="case-alpha",
                description="Alpha route",
                task_input=_ModelRoutePromptInput(prompt="Run alpha."),
            ),
            EvaluationCase(
                id="case-beta",
                description="Beta route",
                task_input=_ModelRoutePromptInput(prompt="Run beta."),
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
            json=_build_chat_completion_payload(
                response_model=f"{route}/model", provider=f"{route}/provider"
            ),
        )

    agent = _build_chat_agent_with_mock_transport(
        deployment,
        handler,
        openrouter_retry_hooks=OpenRouterRetryHooks(
            admission_gate=OpenRouterAdmissionGate(max_concurrency=2)
        ),
    )

    report = run_data_set(
        data_set,
        task=lambda case_input: agent.run_sync(case_input.prompt).output,
        evaluators=(),
        max_concurrency=2,
    )

    assert {case.name: case.attributes["model_routes"] for case in report.cases} == {
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


def test_completed_coreference_report_counts_sequential_resolution_rounds(
    tmp_path: Path, monkeypatch
) -> None:
    """Count annotator, critic, and correction responses at the report seam."""

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-model-route-coreference")
    deployment = _build_openrouter_model_route_deployment()
    data_set = EvaluationDataSet(
        task="coreference",
        description="Sequential Coreference Resolution route cases.",
        cases=(
            EvaluationCase(
                id="case-coreference-rounds",
                description="Coreference Resolution with one correction round",
                task_input=CoreferenceInput(
                    url="https://example.test/alice",
                    title="Alice story",
                    content="Alice signed a bill. She celebrated.",
                ),
            ),
        ),
    )
    stage_calls: dict[str, int] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode()
        if "Alice signed a bill" not in body:
            raise AssertionError("the Coreference Resolution request lost its case")
        if "Correct only the rejected Mention Spans" in body:
            stage = "correction"
        elif "Validated Mention Spans:" in body:
            stage = "critic"
        else:
            stage = "annotator"
        stage_call = stage_calls.get(stage, 0) + 1
        stage_calls[stage] = stage_call

        if stage == "annotator":
            payload = [
                {
                    "sentence_label": "2",
                    "mention_text": "She",
                    "canonical_entity_name": "Unclear Alice",
                }
            ]
        elif stage == "critic":
            payload = [
                {
                    "sentence_label": "2",
                    "mention_text": "She",
                    "accepted": stage_call > 1,
                    **(
                        {"reason": "Use the author's name."}
                        if stage_call == 1
                        else {}
                    ),
                }
            ]
        else:
            payload = [
                {
                    "sentence_label": "2",
                    "mention_text": "She",
                    "canonical_entity_name": "Alice",
                }
            ]

        return httpx.Response(
            200,
            json=_build_structured_chat_completion_payload(
                response_model=deployment.model,
                provider=f"{stage}/provider",
                payload=payload,
            ),
        )

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        coreference_adapter_module,
        "get_chat_model",
        lambda requested: get_chat_model(requested, transport=transport),
    )
    resolve = coreference_task_module.build_task(deployment, data_set)

    report = run_data_set(data_set, task=resolve, evaluators=())

    assert not report.failures
    assert stage_calls == {"annotator": 1, "critic": 2, "correction": 1}
    routes = {
        (entry["response_model"], entry["downstream_provider"]): entry[
            "request_count"
        ]
        for entry in report.cases[0].attributes["model_routes"]
    }
    assert routes == {
        (deployment.model, "annotator/provider"): 1,
        (deployment.model, "critic/provider"): 2,
        (deployment.model, "correction/provider"): 1,
    }

    path = write_report(
        report,
        task="coreference",
        deployment=deployment,
        data_set_path=tmp_path / "relevance.yaml",
        root=tmp_path / "reports",
    )
    serialized_routes = json.loads(path.read_text())["report"]["cases"][0][
        "attributes"
    ]["model_routes"]
    assert {
        (entry["response_model"], entry["downstream_provider"]): entry[
            "request_count"
        ]
        for entry in serialized_routes
    } == routes


def test_request_without_a_response_does_not_contribute_a_route() -> None:
    deployment = _build_local_model_route_deployment()
    agent = _build_chat_agent_with_mock_transport(
        deployment,
        lambda request: httpx.Response(500, json={"error": {"message": "unavailable"}}),
    )

    def task(case_input: _ModelRoutePromptInput) -> str:
        try:
            return agent.run_sync(case_input.prompt).output
        except ModelAPIError:
            return "task fallback"

    report = run_data_set(
        _build_model_route_data_set("case-request-without-response"),
        task=task,
        evaluators=(),
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
    agent = _build_chat_agent_with_mock_transport(
        deployment,
        lambda request: httpx.Response(
            200,
            json=_build_chat_completion_payload(
                response_model="openai/gpt-4o-mini", provider="openai/hosted"
            ),
        ),
    )
    report = run_data_set(
        _build_model_route_data_set("case-complete-report"),
        task=lambda case_input: agent.run_sync(case_input.prompt).output,
        evaluators=(),
    )
    data_set_path = tmp_path / "relevance.yaml"

    path = write_report(
        report,
        task="model-routes",
        deployment=deployment,
        data_set_path=data_set_path,
        split="held-out",
        root=tmp_path / "reports",
    )
    document = json.loads(path.read_text())
    serialized_case = document["report"]["cases"][0]

    assert serialized_case["metrics"]["requests"] == 1
    assert serialized_case["metrics"]["input_tokens"] == 2
    assert serialized_case["metrics"]["output_tokens"] == 3
    assert serialized_case["metrics"]["cost"] > 0
    assert serialized_case["attributes"]["model_routes"] == [
        {
            "response_model": "openai/gpt-4o-mini",
            "downstream_provider": "openai/hosted",
            "request_count": 1,
        }
    ]
    assert "request_provenance" not in serialized_case["attributes"]
    assert "request_provenance_aggregate" not in document["report"]
    assert document["task"] == "model-routes"
    assert document["model"] == deployment.model
    assert document["deployment"] == deployment.model_dump(mode="json")
    assert document["commit"]
    assert isinstance(document["dirty"], bool)
    assert document["data_set"] == str(data_set_path)
    assert document["split"] == "held-out"
