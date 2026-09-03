"""Evaluation Run failure boundaries and report atomicity."""

from __future__ import annotations

import argparse
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic_evals.reporting import EvaluationReport, ReportCase, ReportCaseFailure

from knowledge_map.cli import evaluate


def _arguments(gold_set: Path, *, no_report: bool = False) -> argparse.Namespace:
    return argparse.Namespace(
        eval_action="run",
        task="relevance",
        gold_set=gold_set,
        deployment="openrouter",
        model=None,
        split=None,
        max_concurrency=1,
        no_report=no_report,
    )


def _task() -> SimpleNamespace:
    return SimpleNamespace(
        name="relevance",
        gold_set_stem="relevance",
        input_type=dict,
        output_type=dict,
        metadata_type=dict,
        default_model="local/model",
        build=lambda deployment, gold_set: lambda case_input: {"label": "ok"},
        evaluators=(),
    )


@pytest.fixture
def command_context(tmp_path: Path, monkeypatch) -> tuple[Path, Path]:
    gold_set = tmp_path / "relevance.yaml"
    gold_set.write_text("placeholder")
    report_root = tmp_path / "evals" / "reports"
    report_root.mkdir(parents=True)
    monkeypatch.chdir(tmp_path)

    task = _task()
    monkeypatch.setattr(evaluate, "task_named", lambda name: task)
    monkeypatch.setattr(evaluate, "load_dotenv", lambda: None)
    monkeypatch.setattr(evaluate, "load_gold_set", lambda *args, **kwargs: object())
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-evaluation-test")
    monkeypatch.setenv("OPENROUTER_MODEL", "configured/model")
    monkeypatch.setenv("OPENROUTER_PROVIDERS", "google-ai-studio")
    return gold_set, report_root


def _failed_report(error_message: str) -> EvaluationReport:
    failure = ReportCaseFailure(
        name="case",
        inputs={},
        metadata=None,
        expected_output=None,
        error_message=error_message,
        error_stacktrace="traceback",
    )
    return EvaluationReport(name="relevance", cases=[], failures=[failure])


def _successful_report() -> EvaluationReport:
    return EvaluationReport(
        name="relevance",
        cases=[
            ReportCase(
                name="case",
                inputs={},
                metadata=None,
                expected_output={"label": "ok"},
                output={"label": "ok"},
                metrics={},
                attributes={},
                scores={},
                labels={},
                assertions={},
                task_duration=0.0,
                total_duration=0.0,
            )
        ],
    )


@pytest.mark.parametrize(
    "error_message",
    [
        "rate-limit attempts exhausted",
        "transport attempts exhausted",
        "task attempts exhausted",
    ],
)
def test_exhausted_evaluation_fails_before_report_write(
    command_context: tuple[Path, Path], monkeypatch, capsys, error_message: str
) -> None:
    gold_set, report_root = command_context
    report = _failed_report(error_message)
    monkeypatch.setattr(evaluate, "run_gold_set", lambda *args, **kwargs: report)

    with pytest.raises(SystemExit, match="no report was written"):
        evaluate.dispatch(_arguments(gold_set))

    assert error_message in capsys.readouterr().out
    assert list(report_root.rglob("*.json")) == []


def test_no_report_prints_a_successful_evaluation_without_writing(
    command_context: tuple[Path, Path], monkeypatch, capsys
) -> None:
    gold_set, report_root = command_context
    report = _successful_report()
    monkeypatch.setattr(evaluate, "run_gold_set", lambda *args, **kwargs: report)

    evaluate.dispatch(_arguments(gold_set, no_report=True))

    assert "Evaluation Summary" in capsys.readouterr().out
    assert list(report_root.rglob("*.json")) == []
