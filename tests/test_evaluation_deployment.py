"""Evaluation command boundaries for explicit Model Deployment selection."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from knowledge_map.cli import evaluate
from knowledge_map.evaluation import report_path, write_report
from knowledge_map.schemas import (
    DeploymentKind,
    ModelDeployment,
    OpenRouterProviderPolicy,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="action", required=True)
    evaluate.add_parser(subparsers)
    return parser


def test_evaluation_run_defaults_to_openrouter_deployment() -> None:
    args = _parser().parse_args(["eval", "run", "relevance"])

    assert args.deployment == "openrouter"


@pytest.mark.parametrize("value", ["0", "-1"])
def test_evaluation_run_requires_positive_max_concurrency(value: str) -> None:
    with pytest.raises(SystemExit):
        _parser().parse_args(
            ["eval", "run", "relevance", "--max-concurrency", value]
        )


def test_eval_run_binds_one_model_deployment_to_task_and_report(
    tmp_path: Path, monkeypatch
) -> None:
    calls: dict[str, object] = {}
    gold_set_path = tmp_path / "relevance.yaml"
    gold_set_path.write_text("placeholder")

    def build(deployment: ModelDeployment, gold_set: object):
        calls["task_deployment"] = deployment
        calls["gold_set"] = gold_set
        return lambda case_input: {"classification": "RELEVANT"}

    task = SimpleNamespace(
        name="relevance",
        gold_set_stem="relevance",
        input_type=dict,
        output_type=dict,
        metadata_type=dict,
        build=build,
        evaluators=(),
    )
    report = SimpleNamespace(print=lambda **kwargs: None, failures=())

    monkeypatch.setattr(evaluate, "task_named", lambda name: task)
    monkeypatch.setattr(evaluate, "load_gold_set", lambda *args, **kwargs: object())
    monkeypatch.setattr(evaluate, "run_gold_set", lambda *args, **kwargs: report)

    def capture_report(*args, **kwargs):
        calls["report_deployment"] = kwargs["deployment"]
        return tmp_path / "report.json"

    monkeypatch.setattr(evaluate, "write_report", capture_report)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-evaluation-test")
    monkeypatch.setenv("OPENROUTER_MODEL", "configured/model")
    monkeypatch.setenv("OPENROUTER_PROVIDERS", "google-ai-studio,openai")

    evaluate.dispatch(
        argparse.Namespace(
            eval_action="run",
            task="relevance",
            gold_set=gold_set_path,
            deployment="openrouter",
            model="override/model:verbatim",
            split=None,
            max_concurrency=1,
            no_report=False,
        )
    )

    task_deployment = calls["task_deployment"]
    assert isinstance(task_deployment, ModelDeployment)
    assert task_deployment.kind is DeploymentKind.OPENROUTER
    assert task_deployment.model == "override/model:verbatim"
    assert task_deployment.provider_policy.providers == (
        "google-ai-studio",
        "openai",
    )
    assert calls["report_deployment"] is task_deployment


@dataclass(frozen=True)
class _Report:
    cases: tuple[object, ...] = ()


def test_reports_serialize_deployment_and_separate_local_and_openrouter_runs(
    tmp_path: Path,
) -> None:
    ran_at = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)
    local = ModelDeployment(
        kind=DeploymentKind.LOCAL,
        model="google/gemma-4-26b-a4b-it",
        endpoint="http://localhost:8080/v1",
    )
    openrouter = ModelDeployment(
        kind=DeploymentKind.OPENROUTER,
        model=local.model,
        provider_policy={"providers": ("google-ai-studio", "openai")},
    )

    local_path = report_path(
        "relevance", deployment=local, ran_at=ran_at, root=tmp_path / "paths"
    )
    openrouter_path = report_path(
        "relevance", deployment=openrouter, ran_at=ran_at, root=tmp_path / "paths"
    )
    assert local_path != openrouter_path
    assert "local" in local_path.name
    assert "openrouter" in openrouter_path.name

    written = write_report(
        _Report(),
        task="relevance",
        deployment=openrouter,
        gold_set_path=tmp_path / "gold.yaml",
        root=tmp_path / "reports",
    )
    document = json.loads(written.read_text())

    assert document["deployment"] == openrouter.model_dump(mode="json")
    assert document["model"] == openrouter.model
    assert "OPENROUTER_API_KEY" not in json.dumps(document)


def test_report_filenames_distinguish_openrouter_deployment_identity(
    tmp_path: Path,
) -> None:
    ran_at = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)
    first = ModelDeployment(
        kind=DeploymentKind.OPENROUTER,
        model="google/gemma-4-26b-a4b-it:free",
        provider_policy={"providers": ("google-ai-studio", "openai")},
    )
    second = first.model_copy(
        update={
            "provider_policy": OpenRouterProviderPolicy(
                providers=("openai", "google-ai-studio")
            )
        }
    )

    first_path = report_path(
        "relevance", deployment=first, ran_at=ran_at, root=tmp_path
    )
    second_path = report_path(
        "relevance", deployment=second, ran_at=ran_at, root=tmp_path
    )

    assert first_path != second_path
    assert first_path.parent == second_path.parent


def test_openrouter_provider_list_rejects_empty_entries(monkeypatch) -> None:
    monkeypatch.setattr(evaluate, "load_dotenv", lambda: None)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-evaluation-test")
    monkeypatch.setenv("OPENROUTER_MODEL", "configured/model")
    monkeypatch.setenv("OPENROUTER_PROVIDERS", "google-ai-studio,,openai")

    with pytest.raises(ValueError, match="OPENROUTER_PROVIDERS"):
        evaluate.select_deployment(
            SimpleNamespace(default_model="local/model"), kind="openrouter"
        )


def test_incomplete_openrouter_configuration_fails_before_gold_set_execution(
    tmp_path: Path, monkeypatch
) -> None:
    gold_set_path = tmp_path / "relevance.yaml"
    gold_set_path.write_text("placeholder")
    calls: list[str] = []
    task = SimpleNamespace(
        name="relevance",
        gold_set_stem="relevance",
        default_model="local/model",
    )

    monkeypatch.setattr(evaluate, "task_named", lambda name: task)
    monkeypatch.setattr(
        evaluate,
        "load_gold_set",
        lambda *args, **kwargs: calls.append("gold-set") or object(),
    )
    monkeypatch.setattr(
        evaluate,
        "run_gold_set",
        lambda *args, **kwargs: calls.append("run") or object(),
    )
    monkeypatch.setattr(evaluate, "load_dotenv", lambda: None)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)
    monkeypatch.delenv("OPENROUTER_PROVIDERS", raising=False)

    try:
        evaluate.dispatch(
            argparse.Namespace(
                eval_action="run",
                task="relevance",
                gold_set=gold_set_path,
                deployment="openrouter",
                model=None,
                split=None,
                max_concurrency=1,
                no_report=True,
            )
        )
    except SystemExit as error:
        message = str(error)
    else:
        raise AssertionError("incomplete OpenRouter configuration was accepted")

    assert "OPENROUTER_API_KEY" in message
    assert "OPENROUTER_MODEL" in message
    assert "OPENROUTER_PROVIDERS" in message
    assert calls == []
