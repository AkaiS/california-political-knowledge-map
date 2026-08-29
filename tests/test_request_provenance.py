"""Evaluation request provenance at the real Agent and report seams."""

from __future__ import annotations

import json
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
from knowledge_map.utils.models import get_chat_model


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


def _openrouter_deployment() -> ModelDeployment:
    return ModelDeployment(
        kind=DeploymentKind.OPENROUTER,
        model="google/gemma-4-26b-a4b-it",
        request_settings=ModelRequestSettings(max_attempts=1),
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
        }
    ]
