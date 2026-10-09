"""Evaluation Run failure boundaries and report atomicity."""

from __future__ import annotations

import argparse
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic_evals.reporting import EvaluationReport, ReportCase, ReportCaseFailure

from knowledge_map.cli import evaluate
from knowledge_map.evaluation import EvaluationCase, EvaluationDataSet, LabelQuality


def _arguments(data_set: Path, *, no_report: bool = False) -> argparse.Namespace:
    return argparse.Namespace(
        eval_action="run",
        task="relevance",
        data_set=data_set,
        deployment="openrouter",
        model=None,
        split=None,
        max_concurrency=1,
        no_report=no_report,
    )


def _task() -> SimpleNamespace:
    return SimpleNamespace(
        name="relevance",
        data_set_stem="relevance",
        label_quality=LabelQuality.GOLD,
        prompt_digests=dict,
        input_type=dict,
        output_type=dict,
        metadata_type=dict,
        default_model="local/model",
        build=lambda deployment, data_set: lambda case_input: {"label": "ok"},
        evaluators=(),
    )


@pytest.fixture
def command_context(tmp_path: Path, monkeypatch) -> tuple[Path, Path]:
    data_set = tmp_path / "relevance.yaml"
    data_set.write_text("placeholder")
    report_root = tmp_path / "evals" / "reports"
    report_root.mkdir(parents=True)
    monkeypatch.chdir(tmp_path)

    task = _task()
    monkeypatch.setattr(evaluate, "task_named", lambda name: task)
    monkeypatch.setattr(evaluate, "load_dotenv", lambda: None)
    monkeypatch.setattr(
        evaluate,
        "load_data_set",
        lambda *args, **kwargs: EvaluationDataSet(
            task="relevance",
            description="test",
            cases=(
                EvaluationCase(
                    id="case",
                    description="test",
                    task_input={},
                    expected_output={},
                ),
            ),
        ),
    )
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-evaluation-test")
    monkeypatch.setenv("OPENROUTER_MODEL", "configured/model")
    monkeypatch.setenv("OPENROUTER_PROVIDERS", "google-ai-studio")
    return data_set, report_root


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
def test_exhausted_evaluation_preserves_report_before_exit(
    command_context: tuple[Path, Path], monkeypatch, capsys, error_message: str
) -> None:
    data_set, report_root = command_context
    report = _failed_report(error_message)
    monkeypatch.setattr(evaluate, "run_data_set", lambda *args, **kwargs: report)

    with pytest.raises(SystemExit, match="report preserved"):
        evaluate.dispatch(_arguments(data_set))

    assert error_message in capsys.readouterr().out
    import json

    documents = [json.loads(path.read_text()) for path in report_root.rglob("*.json")]
    assert len(documents) == 1
    assert documents[0]["evaluation_run"]["status"] == "completed"
    assert documents[0]["evaluation_run"]["unresolved_case_ids"] == []
    assert documents[0]["report"]["failures"][0]["error_message"] == error_message


def test_no_report_prints_a_successful_evaluation_without_writing(
    command_context: tuple[Path, Path], monkeypatch, capsys
) -> None:
    data_set, report_root = command_context
    report = _successful_report()
    monkeypatch.setattr(evaluate, "run_data_set", lambda *args, **kwargs: report)

    evaluate.dispatch(_arguments(data_set, no_report=True))

    assert "Evaluation Summary" in capsys.readouterr().out
    assert list(report_root.rglob("*.json")) == []


def test_report_printing_error_cannot_discard_finished_report(
    command_context: tuple[Path, Path], monkeypatch
) -> None:
    import json

    data_set, report_root = command_context
    report = _successful_report()
    monkeypatch.setattr(evaluate, "run_data_set", lambda *args, **kwargs: report)

    def broken_print(*args, **kwargs):
        raise RuntimeError("terminal rendering failed")

    monkeypatch.setattr(report, "print", broken_print)
    with pytest.raises(RuntimeError, match="terminal rendering failed"):
        evaluate.dispatch(_arguments(data_set))
    saved = [json.loads(path.read_text()) for path in report_root.rglob("*.json")]
    assert len(saved) == 1
    assert saved[0]["evaluation_run"]["status"] == "completed"
    assert saved[0]["report"]["cases"][0]["output"] == {"label": "ok"}


@pytest.mark.parametrize("kind", ["stage", "case_evaluator", "report_evaluator"])
def test_execution_or_evaluator_error_returns_nonzero_after_saving(
    command_context: tuple[Path, Path], monkeypatch, kind: str
) -> None:
    import json

    from pydantic_evals.evaluators import EvaluatorFailure

    data_set, report_root = command_context
    report = _successful_report()
    if kind == "stage":
        report.cases[0].output["failure"] = {
            "stage": "guidance",
            "message": "generation failed",
        }
    else:
        failure = EvaluatorFailure(
            name="judge",
            error_message="judge error",
            error_stacktrace="traceback",
            source={"name": "judge"},
        )
        if kind == "case_evaluator":
            report.cases[0].evaluator_failures.append(failure)
        else:
            report.report_evaluator_failures.append(failure)
    monkeypatch.setattr(evaluate, "run_data_set", lambda *args, **kwargs: report)
    with pytest.raises(SystemExit, match="report preserved"):
        evaluate.dispatch(_arguments(data_set))
    saved = [json.loads(path.read_text()) for path in report_root.rglob("*.json")]
    assert len(saved) == 1
    assert saved[0]["evaluation_run"]["status"] == "completed"
    assert saved[0]["evaluation_run"]["terminal_count"] == 1


def test_a_negative_quality_judgment_is_a_completed_evaluation(
    command_context: tuple[Path, Path], monkeypatch
) -> None:
    from pydantic_evals.evaluators import EvaluationResult

    data_set, report_root = command_context
    report = _successful_report()
    report.cases[0].scores["quality"] = EvaluationResult(
        name="quality", value=0.0, reason="incorrect answer", source={"name": "judge"}
    )
    monkeypatch.setattr(evaluate, "run_data_set", lambda *args, **kwargs: report)
    evaluate.dispatch(_arguments(data_set))
    assert len(list(report_root.rglob("*.json"))) == 1
