"""Evaluation request provenance at the real Agent and report seams."""

from __future__ import annotations

import json
import threading
from decimal import Decimal
from pathlib import Path

import httpx
from pydantic import BaseModel
from pydantic_ai import Agent

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


def _gold_set(case_id: str = "case-route") -> EvaluationGoldSet:
    return EvaluationGoldSet(
        task="provenance",
        description="A request provenance test set.",
        cases=(
            EvaluationCase(
                id=case_id,
                description="One request",
                task_input=_PromptInput(prompt="Resolve this."),
            ),
        ),
    )


def _openrouter_deployment(*, max_attempts: int = 1) -> ModelDeployment:
    return ModelDeployment(
        kind=DeploymentKind.OPENROUTER,
        model="google/gemma-4-26b-a4b-it",
        request_settings=ModelRequestSettings(max_attempts=max_attempts),
        provider_policy=OpenRouterProviderPolicy(providers=("google-ai-studio",)),
    )


def _completion(*, model: str, response_id: str, provider: str) -> dict:
    return {
        "id": response_id,
        "object": "chat.completion",
        "created": 0,
        "model": model,
        "provider": provider,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "resolved"},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 1,
            "completion_tokens": 1,
            "total_tokens": 2,
            "is_byok": True,
        },
    }


def _completion_with_usage(
    *, model: str, response_id: str, provider: str, usage: dict
) -> dict:
    response = _completion(
        model=model,
        response_id=response_id,
        provider=provider,
    )
    response["usage"] = usage
    return response


def test_openrouter_route_provenance_reaches_the_case_report(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-provenance-secret")
    deployment = _openrouter_deployment()

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            json=_completion(
                model="google/gemma-4-26b-a4b-it",
                response_id="generation-123",
                provider="google-ai-studio/vertex-test",
            ),
        )

    agent = Agent(
        get_chat_model(deployment, transport=httpx.MockTransport(handler)),
        name="provenance_openrouter_agent",
        output_type=str,
        defer_model_check=True,
    )
    report = run_gold_set(
        _gold_set(),
        task=lambda case_input: agent.run_sync(case_input.prompt).output,
        evaluators=(),
    )

    expected = {
        "case_id": "case-route",
        "deployment": "openrouter",
        "requested_model": "google/gemma-4-26b-a4b-it",
        "returned_model": "google/gemma-4-26b-a4b-it",
        "downstream_provider": "google-ai-studio/vertex-test",
        "generation_id": "generation-123",
        "is_byok": True,
        "input_tokens": 1,
        "output_tokens": 1,
        "reasoning_tokens": None,
        "cache_write_tokens": None,
        "cache_read_tokens": None,
        "total_tokens": 2,
        "charged_cost": None,
        "upstream_cost": None,
        "route_attempts": None,
        "attempts": 1,
        "retry_count": 0,
        "rate_limit_wait": 0.0,
    }
    assert report.cases[0].attributes["request_provenance"] == [expected]

    path = write_report(
        report,
        task="provenance",
        deployment=deployment,
        gold_set_path=tmp_path / "gold.yaml",
        root=tmp_path / "reports",
    )
    document = json.loads(path.read_text())
    assert document["report"]["cases"][0]["attributes"]["request_provenance"] == [
        expected
    ]
    assert "sk-provenance-secret" not in json.dumps(document)


def test_failed_case_keeps_request_provenance_in_report(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-provenance-failure-secret")
    deployment = _openrouter_deployment()

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            json=_completion(
                model="google/gemma-4-26b-a4b-it",
                response_id="generation-before-failure",
                provider="google-ai-studio/vertex-test",
            ),
        )

    agent = Agent(
        get_chat_model(deployment, transport=httpx.MockTransport(handler)),
        name="provenance_failure_agent",
        output_type=str,
        defer_model_check=True,
    )

    def task(case_input: _PromptInput) -> str:
        agent.run_sync(case_input.prompt)
        raise RuntimeError("task failed after the model response")

    report = run_gold_set(_gold_set("case-failure"), task=task, evaluators=())
    expected = {
        "case_id": "case-failure",
        "deployment": "openrouter",
        "requested_model": "google/gemma-4-26b-a4b-it",
        "returned_model": "google/gemma-4-26b-a4b-it",
        "downstream_provider": "google-ai-studio/vertex-test",
        "generation_id": "generation-before-failure",
        "is_byok": True,
        "input_tokens": 1,
        "output_tokens": 1,
        "reasoning_tokens": None,
        "cache_write_tokens": None,
        "cache_read_tokens": None,
        "total_tokens": 2,
        "charged_cost": None,
        "upstream_cost": None,
        "route_attempts": None,
        "attempts": 1,
        "retry_count": 0,
        "rate_limit_wait": 0.0,
    }

    assert len(report.failures) == 1
    assert report.failures[0].request_provenance == [expected]

    path = write_report(
        report,
        task="provenance",
        deployment=deployment,
        gold_set_path=tmp_path / "gold.yaml",
        root=tmp_path / "reports",
    )
    document = json.loads(path.read_text())
    assert document["report"]["failures"][0]["request_provenance"] == [expected]
    assert "sk-provenance-failure-secret" not in json.dumps(document)


def test_shared_input_objects_keep_their_authored_case_route_association(
    monkeypatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-provenance-shared-input")
    deployment = _openrouter_deployment()
    response_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal response_count
        del request
        response_count += 1
        return httpx.Response(
            200,
            json=_completion(
                model="google/gemma-4-26b-a4b-it",
                response_id=f"generation-shared-{response_count}",
                provider="google-ai-studio/vertex-test",
            ),
        )

    agent = Agent(
        get_chat_model(deployment, transport=httpx.MockTransport(handler)),
        name="provenance_shared_input_agent",
        output_type=str,
        defer_model_check=True,
    )
    shared_input = _PromptInput(prompt="Resolve this shared input.")
    gold_set = EvaluationGoldSet(
        task="provenance",
        description="Two authored cases sharing one input object.",
        cases=(
            EvaluationCase(
                id="case-shared-first",
                description="First shared-input request",
                task_input=shared_input,
            ),
            EvaluationCase(
                id="case-shared-second",
                description="Second shared-input request",
                task_input=shared_input,
            ),
        ),
    )

    report = run_gold_set(
        gold_set,
        task=lambda case_input: agent.run_sync(case_input.prompt).output,
        evaluators=(),
    )

    assert [
        case.attributes["request_provenance"][0]["case_id"]
        for case in report.cases
    ] == ["case-shared-first", "case-shared-second"]


def test_missing_openrouter_route_facts_are_unavailable(
    monkeypatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-provenance-missing")
    deployment = _openrouter_deployment()

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        response = _completion(
            model="google/gemma-4-26b-a4b-it",
            response_id="generation-without-byok",
            provider="",
        )
        del response["usage"]
        return httpx.Response(200, json=response)

    agent = Agent(
        get_chat_model(deployment, transport=httpx.MockTransport(handler)),
        name="provenance_missing_agent",
        output_type=str,
        defer_model_check=True,
    )
    report = run_gold_set(
        _gold_set("case-missing-route"),
        task=lambda case_input: agent.run_sync(case_input.prompt).output,
        evaluators=(),
    )

    assert report.cases[0].attributes["request_provenance"] == [
        {
            "case_id": "case-missing-route",
            "deployment": "openrouter",
            "requested_model": "google/gemma-4-26b-a4b-it",
            "returned_model": "google/gemma-4-26b-a4b-it",
            "downstream_provider": None,
            "generation_id": "generation-without-byok",
            "is_byok": None,
            "input_tokens": None,
            "output_tokens": None,
            "reasoning_tokens": None,
            "cache_write_tokens": None,
            "cache_read_tokens": None,
            "total_tokens": None,
            "charged_cost": None,
            "upstream_cost": None,
            "route_attempts": None,
            "attempts": 1,
            "retry_count": 0,
            "rate_limit_wait": 0.0,
        }
    ]


def test_missing_openrouter_provider_does_not_invent_a_route(
    monkeypatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-provenance-no-provider")
    deployment = _openrouter_deployment()

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        response = _completion(
            model="google/gemma-4-26b-a4b-it",
            response_id="generation-without-provider",
            provider="unused",
        )
        del response["provider"]
        del response["usage"]
        return httpx.Response(200, json=response)

    agent = Agent(
        get_chat_model(deployment, transport=httpx.MockTransport(handler)),
        name="provenance_no_provider_agent",
        output_type=str,
        defer_model_check=True,
    )
    report = run_gold_set(
        _gold_set("case-no-provider"),
        task=lambda case_input: agent.run_sync(case_input.prompt).output,
        evaluators=(),
    )

    assert report.cases[0].attributes["request_provenance"][0][
        "downstream_provider"
    ] is None


def test_local_route_provenance_identifies_llama_cpp_and_not_remote_facts(
    monkeypatch,
) -> None:
    deployment = ModelDeployment(
        kind=DeploymentKind.LOCAL,
        model="google/gemma-4-26b-a4b-it",
        endpoint="http://llama.test/v1",
        request_settings=ModelRequestSettings(max_attempts=1),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            json=_completion(
                model="google/gemma-4-26b-a4b-it",
                response_id="local-response",
                provider="unused-local-provider",
            ),
        )

    agent = Agent(
        get_chat_model(deployment, transport=httpx.MockTransport(handler)),
        name="provenance_local_agent",
        output_type=str,
        defer_model_check=True,
    )
    report = run_gold_set(
        _gold_set("case-local"),
        task=lambda case_input: agent.run_sync(case_input.prompt).output,
        evaluators=(),
    )

    assert report.cases[0].attributes["request_provenance"] == [
        {
            "case_id": "case-local",
            "deployment": "llama.cpp",
            "requested_model": "google/gemma-4-26b-a4b-it",
            "returned_model": "google/gemma-4-26b-a4b-it",
            "downstream_provider": None,
            "generation_id": None,
            "is_byok": None,
            "input_tokens": 1,
            "output_tokens": 1,
            "reasoning_tokens": None,
            "cache_write_tokens": None,
            "cache_read_tokens": None,
            "total_tokens": 2,
            "charged_cost": None,
            "upstream_cost": None,
            "route_attempts": None,
            "attempts": 1,
            "retry_count": 0,
            "rate_limit_wait": 0.0,
        }
    ]


def test_openrouter_usage_and_cost_provenance_reaches_serialized_case_report(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-token-cost-secret")
    deployment = _openrouter_deployment()

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            json=_completion_with_usage(
                model="google/gemma-4-26b-a4b-it",
                response_id="generation-token-cost",
                provider="google-ai-studio/vertex-test",
                usage={
                    "prompt_tokens": 11,
                    "completion_tokens": 7,
                    "total_tokens": 18,
                    "prompt_tokens_details": {
                        "cached_tokens": 3,
                        "cache_write_tokens": 2,
                    },
                    "completion_tokens_details": {"reasoning_tokens": 5},
                    "cost": 0.0012,
                    "cost_details": {"upstream_inference_cost": 0.0008},
                    "is_byok": True,
                },
            ),
        )

    agent = Agent(
        get_chat_model(deployment, transport=httpx.MockTransport(handler)),
        name="token_cost_openrouter_agent",
        output_type=str,
        defer_model_check=True,
    )
    report = run_gold_set(
        _gold_set("case-token-cost"),
        task=lambda case_input: agent.run_sync(case_input.prompt).output,
        evaluators=(),
    )
    expected = {
        "case_id": "case-token-cost",
        "deployment": "openrouter",
        "requested_model": "google/gemma-4-26b-a4b-it",
        "returned_model": "google/gemma-4-26b-a4b-it",
        "downstream_provider": "google-ai-studio/vertex-test",
        "generation_id": "generation-token-cost",
        "is_byok": True,
        "input_tokens": 11,
        "output_tokens": 7,
        "reasoning_tokens": 5,
        "cache_write_tokens": 2,
        "cache_read_tokens": 3,
        "total_tokens": 18,
        "charged_cost": Decimal("0.0012"),
        "upstream_cost": Decimal("0.0008"),
        "route_attempts": None,
        "attempts": 1,
        "retry_count": 0,
        "rate_limit_wait": 0.0,
    }

    assert report.cases[0].attributes["request_provenance"] == [expected]

    path = write_report(
        report,
        task="provenance",
        deployment=deployment,
        gold_set_path=tmp_path / "gold.yaml",
        root=tmp_path / "reports",
    )
    document = json.loads(path.read_text())
    expected_serialized = expected | {
        "charged_cost": "0.0012",
        "upstream_cost": "0.0008",
    }
    assert document["report"]["cases"][0]["attributes"]["request_provenance"] == [
        expected_serialized
    ]
    serialized_record = document["report"]["cases"][0]["attributes"][
        "request_provenance"
    ][0]
    assert serialized_record["charged_cost"] == "0.0012"
    assert serialized_record["upstream_cost"] == "0.0008"
    assert "sk-token-cost-secret" not in json.dumps(document)


def test_missing_usage_categories_and_costs_remain_unavailable(
    monkeypatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-token-cost-missing")
    deployment = _openrouter_deployment()

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            json=_completion_with_usage(
                model="google/gemma-4-26b-a4b-it",
                response_id="generation-token-cost-partial",
                provider="google-ai-studio/vertex-test",
                usage={
                    "prompt_tokens": 4,
                    "completion_tokens": 6,
                    "total_tokens": 10,
                },
            ),
        )

    agent = Agent(
        get_chat_model(deployment, transport=httpx.MockTransport(handler)),
        name="token_cost_missing_agent",
        output_type=str,
        defer_model_check=True,
    )
    report = run_gold_set(
        _gold_set("case-token-cost-partial"),
        task=lambda case_input: agent.run_sync(case_input.prompt).output,
        evaluators=(),
    )

    assert report.cases[0].attributes["request_provenance"] == [
        {
            "case_id": "case-token-cost-partial",
            "deployment": "openrouter",
            "requested_model": "google/gemma-4-26b-a4b-it",
            "returned_model": "google/gemma-4-26b-a4b-it",
            "downstream_provider": "google-ai-studio/vertex-test",
            "generation_id": "generation-token-cost-partial",
            "is_byok": None,
            "input_tokens": 4,
            "output_tokens": 6,
            "reasoning_tokens": None,
            "cache_write_tokens": None,
            "cache_read_tokens": None,
            "total_tokens": 10,
            "charged_cost": None,
            "upstream_cost": None,
            "route_attempts": None,
            "attempts": 1,
            "retry_count": 0,
            "rate_limit_wait": 0.0,
        }
    ]


def test_nested_openrouter_provider_usage_matches_selected_completion(
    monkeypatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-token-cost-nested")
    deployment = _openrouter_deployment()
    response = _completion_with_usage(
        model="google/gemma-4-26b-a4b-it",
        response_id="outer-generation",
        provider="outer-provider",
        usage={"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
    )
    response["provider"] = _completion_with_usage(
        model="google/gemma-4-26b-a4b-it",
        response_id="nested-generation",
        provider="nested-provider",
        usage={"prompt_tokens": 11, "completion_tokens": 12},
    )

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json=response)

    agent = Agent(
        get_chat_model(deployment, transport=httpx.MockTransport(handler)),
        name="token_cost_nested_agent",
        output_type=str,
        defer_model_check=True,
    )
    report = run_gold_set(
        _gold_set("case-token-cost-nested"),
        task=lambda case_input: agent.run_sync(case_input.prompt).output,
        evaluators=(),
    )

    record = report.cases[0].attributes["request_provenance"][0]
    assert record["returned_model"] == "google/gemma-4-26b-a4b-it"
    assert record["downstream_provider"] == "nested-provider"
    assert record["generation_id"] == "nested-generation"
    assert record["input_tokens"] == 11
    assert record["output_tokens"] == 12
    assert record["total_tokens"] is None


def test_partial_usage_preserves_available_tokens_and_missing_total(
    monkeypatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-token-cost-partial-usage")
    deployment = _openrouter_deployment()

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            json=_completion_with_usage(
                model="google/gemma-4-26b-a4b-it",
                response_id="generation-token-cost-partial-usage",
                provider="google-ai-studio/vertex-test",
                usage={"prompt_tokens": 4, "completion_tokens": 6},
            ),
        )

    agent = Agent(
        get_chat_model(deployment, transport=httpx.MockTransport(handler)),
        name="token_cost_partial_usage_agent",
        output_type=str,
        defer_model_check=True,
    )
    report = run_gold_set(
        _gold_set("case-token-cost-partial-usage"),
        task=lambda case_input: agent.run_sync(case_input.prompt).output,
        evaluators=(),
    )

    assert report.cases[0].attributes["request_provenance"] == [
        {
            "case_id": "case-token-cost-partial-usage",
            "deployment": "openrouter",
            "requested_model": "google/gemma-4-26b-a4b-it",
            "returned_model": "google/gemma-4-26b-a4b-it",
            "downstream_provider": "google-ai-studio/vertex-test",
            "generation_id": "generation-token-cost-partial-usage",
            "is_byok": None,
            "input_tokens": 4,
            "output_tokens": 6,
            "reasoning_tokens": None,
            "cache_write_tokens": None,
            "cache_read_tokens": None,
            "total_tokens": None,
            "charged_cost": None,
            "upstream_cost": None,
            "route_attempts": None,
            "attempts": 1,
            "retry_count": 0,
            "rate_limit_wait": 0.0,
        }
    ]


def test_local_usage_provenance_keeps_tokens_but_not_billed_cost(
    monkeypatch,
) -> None:
    deployment = ModelDeployment(
        kind=DeploymentKind.LOCAL,
        model="google/gemma-4-26b-a4b-it",
        endpoint="http://llama.test/v1",
        request_settings=ModelRequestSettings(max_attempts=1),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            json=_completion_with_usage(
                model="google/gemma-4-26b-a4b-it",
                response_id="local-token-cost",
                provider="unused-local-provider",
                usage={
                    "prompt_tokens": 8,
                    "completion_tokens": 5,
                    "total_tokens": 13,
                    "prompt_tokens_details": {
                        "cached_tokens": 2,
                        "cache_write_tokens": 1,
                    },
                    "completion_tokens_details": {"reasoning_tokens": 4},
                    "cost": 0.004,
                    "cost_details": {"upstream_inference_cost": 0.003},
                },
            ),
        )

    agent = Agent(
        get_chat_model(deployment, transport=httpx.MockTransport(handler)),
        name="token_cost_local_agent",
        output_type=str,
        defer_model_check=True,
    )
    report = run_gold_set(
        _gold_set("case-token-cost-local"),
        task=lambda case_input: agent.run_sync(case_input.prompt).output,
        evaluators=(),
    )

    assert report.cases[0].attributes["request_provenance"] == [
        {
            "case_id": "case-token-cost-local",
            "deployment": "llama.cpp",
            "requested_model": "google/gemma-4-26b-a4b-it",
            "returned_model": "google/gemma-4-26b-a4b-it",
            "downstream_provider": None,
            "generation_id": None,
            "is_byok": None,
            "input_tokens": 8,
            "output_tokens": 5,
            "reasoning_tokens": 4,
            "cache_write_tokens": 1,
            "cache_read_tokens": 2,
            "total_tokens": 13,
            "charged_cost": None,
            "upstream_cost": None,
            "route_attempts": None,
            "attempts": 1,
            "retry_count": 0,
            "rate_limit_wait": 0.0,
        }
    ]


def test_retry_provenance_separates_router_attempts_from_application_retries(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-retry-provenance-secret")
    deployment = _openrouter_deployment(max_attempts=3)
    clock = {"now": 1_700_000_000.0, "waits": []}

    def now() -> float:
        return clock["now"]

    async def sleep(delay: float) -> None:
        clock["waits"].append(delay)
        clock["now"] += delay

    hooks = OpenRouterRetryHooks(
        now=now,
        sleep=sleep,
        jitter=lambda upper_bound: upper_bound,
        admission_gate=OpenRouterAdmissionGate(),
    )
    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        del request
        request_count += 1
        if request_count < 3:
            return httpx.Response(
                429,
                headers={"Retry-After": "4" if request_count == 1 else "6"},
                json={"error": {"message": "rate limited", "code": 429}},
            )
        response = _completion(
            model="google/gemma-4-26b-a4b-it",
            response_id="generation-retry-provenance",
            provider="google-ai-studio/vertex-test",
        )
        response["openrouter_metadata"] = {
            "attempt": 2,
            "attempts": [
                {"provider": "google-ai-studio/first", "status": 429},
                {"provider": "google-ai-studio/second", "status": 200},
            ],
        }
        return httpx.Response(200, json=response)

    agent = Agent(
        get_chat_model(
            deployment,
            transport=httpx.MockTransport(handler),
            openrouter_retry_hooks=hooks,
        ),
        name="retry_provenance_agent",
        output_type=str,
        defer_model_check=True,
    )
    report = run_gold_set(
        _gold_set("case-retry-provenance"),
        task=lambda case_input: agent.run_sync(case_input.prompt).output,
        evaluators=(),
    )
    record = report.cases[0].attributes["request_provenance"][0]

    assert request_count == 3
    assert clock["waits"] == [4.0, 6.0]
    assert record["route_attempts"] == 2
    assert record["attempts"] == 3
    assert record["retry_count"] == 2
    assert record["rate_limit_wait"] == 10.0

    path = write_report(
        report,
        task="provenance",
        deployment=deployment,
        gold_set_path=tmp_path / "gold.yaml",
        root=tmp_path / "reports",
    )
    document = json.loads(path.read_text())
    serialized_record = document["report"]["cases"][0]["attributes"][
        "request_provenance"
    ][0]
    assert serialized_record["route_attempts"] == 2
    assert serialized_record["attempts"] == 3
    assert serialized_record["retry_count"] == 2
    assert serialized_record["rate_limit_wait"] == 10.0
    assert "sk-retry-provenance-secret" not in json.dumps(document)


def test_non_rate_retry_has_no_route_attempt_or_rate_wait_inference(
    monkeypatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-retry-provenance-no-rate")
    deployment = _openrouter_deployment(max_attempts=2)
    clock = {"now": 1_700_000_000.0, "sleeps": []}
    hooks = OpenRouterRetryHooks(
        now=lambda: clock["now"],
        sleep=lambda delay: _record_sleep(clock, delay),
        admission_gate=OpenRouterAdmissionGate(),
    )
    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        del request
        request_count += 1
        if request_count == 1:
            return httpx.Response(
                503,
                json={"error": {"message": "temporary", "code": 503}},
            )
        return httpx.Response(
            200,
            json=_completion(
                model="google/gemma-4-26b-a4b-it",
                response_id="generation-non-rate-retry",
                provider="google-ai-studio/vertex-test",
            ),
        )

    agent = Agent(
        get_chat_model(
            deployment,
            transport=httpx.MockTransport(handler),
            openrouter_retry_hooks=hooks,
        ),
        name="non_rate_retry_provenance_agent",
        output_type=str,
        defer_model_check=True,
    )
    report = run_gold_set(
        _gold_set("case-non-rate-retry"),
        task=lambda case_input: agent.run_sync(case_input.prompt).output,
        evaluators=(),
    )
    record = report.cases[0].attributes["request_provenance"][0]

    assert request_count == 2
    assert clock["sleeps"] == []
    assert record["route_attempts"] is None
    assert record["attempts"] == 2
    assert record["retry_count"] == 1
    assert record["rate_limit_wait"] == 0.0


def test_concurrent_case_records_keep_their_retry_state_separate(monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-concurrent-provenance")
    deployment = _openrouter_deployment(max_attempts=2)
    gold_set = EvaluationGoldSet(
        task="provenance",
        description="Concurrent retry provenance cases.",
        cases=(
            EvaluationCase(
                id="case-retried",
                description="A request with one application retry",
                task_input=_PromptInput(prompt="retry this request"),
            ),
            EvaluationCase(
                id="case-direct",
                description="A request without an application retry",
                task_input=_PromptInput(prompt="send this directly"),
            ),
        ),
    )
    barrier = threading.Barrier(2)
    lock = threading.Lock()
    request_counts = {"retry this request": 0, "send this directly": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        prompt = body["messages"][-1]["content"]
        with lock:
            request_counts[prompt] += 1
            request_number = request_counts[prompt]
        if request_number == 1:
            barrier.wait(timeout=5)
        if prompt == "retry this request" and request_number == 1:
            return httpx.Response(
                503,
                json={"error": {"message": "temporary", "code": 503}},
            )
        response = _completion(
            model="google/gemma-4-26b-a4b-it",
            response_id=f"generation-{prompt}",
            provider="google-ai-studio/vertex-test",
        )
        if prompt == "retry this request":
            response["openrouter_metadata"] = {
                "attempt": 4,
                "attempts": [
                    {"provider": "google-ai-studio/one", "status": 503},
                    {"provider": "google-ai-studio/two", "status": 200},
                    {"provider": "google-ai-studio/three", "status": 200},
                    {"provider": "google-ai-studio/four", "status": 200},
                ],
            }
        return httpx.Response(200, json=response)

    agent = Agent(
        get_chat_model(
            deployment,
            transport=httpx.MockTransport(handler),
            openrouter_retry_hooks=OpenRouterRetryHooks(
                admission_gate=OpenRouterAdmissionGate(max_concurrency=2),
            ),
        ),
        name="concurrent_provenance_agent",
        output_type=str,
        defer_model_check=True,
    )
    report = run_gold_set(
        gold_set,
        task=lambda case_input: agent.run_sync(case_input.prompt).output,
        evaluators=(),
        max_concurrency=2,
    )

    records = {
        case.name: case.attributes["request_provenance"][0]
        for case in report.cases
    }
    assert request_counts == {"retry this request": 2, "send this directly": 1}
    assert records["case-retried"]["route_attempts"] == 4
    assert records["case-retried"]["attempts"] == 2
    assert records["case-retried"]["retry_count"] == 1
    assert records["case-retried"]["rate_limit_wait"] == 0.0
    assert records["case-direct"]["route_attempts"] is None
    assert records["case-direct"]["attempts"] == 1
    assert records["case-direct"]["retry_count"] == 0
    assert records["case-direct"]["rate_limit_wait"] == 0.0


def test_exhausted_openrouter_retry_keeps_attempt_provenance_on_failure(
    monkeypatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-retry-provenance-exhausted")
    deployment = _openrouter_deployment(max_attempts=2)
    clock = {"now": 1_700_000_000.0, "waits": []}

    async def sleep(delay: float) -> None:
        clock["waits"].append(delay)
        clock["now"] += delay

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            429,
            headers={"Retry-After": "4"},
            json={"error": {"message": "rate limited", "code": 429}},
        )

    agent = Agent(
        get_chat_model(
            deployment,
            transport=httpx.MockTransport(handler),
            openrouter_retry_hooks=OpenRouterRetryHooks(
                now=lambda: clock["now"],
                sleep=sleep,
                admission_gate=OpenRouterAdmissionGate(),
            ),
        ),
        name="exhausted_retry_provenance_agent",
        output_type=str,
        defer_model_check=True,
    )
    report = run_gold_set(
        _gold_set("case-retry-provenance-exhausted"),
        task=lambda case_input: agent.run_sync(case_input.prompt).output,
        evaluators=(),
    )

    assert len(report.failures) == 1
    assert report.failures[0].request_provenance == [
        {
            "case_id": "case-retry-provenance-exhausted",
            "deployment": "openrouter",
            "requested_model": "google/gemma-4-26b-a4b-it",
            "returned_model": None,
            "downstream_provider": None,
            "generation_id": None,
            "is_byok": None,
            "input_tokens": None,
            "output_tokens": None,
            "reasoning_tokens": None,
            "cache_write_tokens": None,
            "cache_read_tokens": None,
            "total_tokens": None,
            "charged_cost": None,
            "upstream_cost": None,
            "route_attempts": None,
            "attempts": 2,
            "retry_count": 1,
            "rate_limit_wait": 4.0,
        }
    ]
    assert clock["waits"] == [4.0]


def test_local_transport_retries_are_kept_in_request_provenance(monkeypatch) -> None:
    deployment = ModelDeployment(
        kind=DeploymentKind.LOCAL,
        model="google/gemma-4-26b-a4b-it",
        endpoint="http://llama.test/v1",
        request_settings=ModelRequestSettings(max_attempts=2),
    )
    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        del request
        request_count += 1
        if request_count == 1:
            return httpx.Response(
                503,
                json={"error": {"message": "temporary", "code": 503}},
            )
        return httpx.Response(
            200,
            json=_completion(
                model="google/gemma-4-26b-a4b-it",
                response_id="local-retry-provenance",
                provider="unused-local-provider",
            ),
        )

    agent = Agent(
        get_chat_model(deployment, transport=httpx.MockTransport(handler)),
        name="local_retry_provenance_agent",
        output_type=str,
        defer_model_check=True,
    )
    report = run_gold_set(
        _gold_set("case-local-retry-provenance"),
        task=lambda case_input: agent.run_sync(case_input.prompt).output,
        evaluators=(),
    )

    assert request_count == 2
    record = report.cases[0].attributes["request_provenance"][0]
    assert record["deployment"] == "llama.cpp"
    assert record["attempts"] == 2
    assert record["retry_count"] == 1
    assert record["rate_limit_wait"] == 0.0


async def _record_sleep(clock: dict[str, object], delay: float) -> None:
    sleeps = clock["sleeps"]
    assert isinstance(sleeps, list)
    sleeps.append(delay)
