"""Durability through framework lifecycle events and command interruptions."""

from __future__ import annotations

import argparse
import json
from types import SimpleNamespace

import pytest
from pydantic_evals.evaluators import Evaluator, EvaluatorContext
from pydantic_evals.lifecycle import CaseLifecycle
from pydantic_evals.reporting import EvaluationReport, ReportCase

from knowledge_map.cli import evaluate
from knowledge_map.evaluation import (
    EvaluationCase,
    EvaluationDataSet,
    LabelQuality,
    run_data_set,
)
from knowledge_map.evaluation.persistence import ReportCheckpoint
from knowledge_map.evaluation.report_file import atomic_write_document
from knowledge_map.evaluation.tasks.relevance import RELEVANCE_HEADLINE
from knowledge_map.schemas import DeploymentKind, ModelDeployment


def _data_set(count=3):
    return EvaluationDataSet(
        task="test",
        description="durability",
        cases=tuple(
            EvaluationCase(
                id=f"case-{n}", description="test", task_input=n, expected_output=n
            )
            for n in range(count)
        ),
    )


def _checkpoint(tmp_path, data_set):
    path = tmp_path / "data.yaml"
    path.write_text("selected data set")
    return ReportCheckpoint(
        task=data_set.task,
        cases=data_set.cases,
        deployment=ModelDeployment(kind=DeploymentKind.LOCAL, model="test-model"),
        data_set_path=path,
        label_quality=LabelQuality.GOLD,
        experiment_metadata={"prompts": {"test": "digest"}},
        root=tmp_path / "reports",
    )


def _read(checkpoint):
    return json.loads(checkpoint.path.read_text())


@pytest.fixture(autouse=True)
def disable_telemetry(monkeypatch):
    monkeypatch.setattr("knowledge_map.evaluation.engine.setup_telemetry", lambda: None)


def test_checkpoint_exists_before_calls_and_retains_completed_case_during_run(tmp_path):
    data_set = _data_set()
    checkpoint = _checkpoint(tmp_path, data_set)
    initial = _read(checkpoint)
    assert initial["evaluation_run"]["selected_case_ids"] == [
        "case-0",
        "case-1",
        "case-2",
    ]
    assert initial["evaluation_run"]["started_count"] == 0
    assert initial["experiment_metadata"]["prompts"] == {"test": "digest"}
    assert initial["data_set_sha256"]

    def task(value):
        if value == 1:
            saved = _read(checkpoint)
            assert saved["evaluation_run"]["status"] == "running"
            assert saved["evaluation_run"]["terminal_count"] == 1
            assert saved["report"]["cases"][0]["output"] == 0
            assert saved["evaluation_run"]["unresolved_case_ids"] == [
                "case-1",
                "case-2",
            ]
        if value == 2:
            raise RuntimeError("transport exhausted")
        return value

    report = run_data_set(
        data_set,
        task=task,
        evaluators=(),
        case_lifecycle=CaseLifecycle,
        checkpoint=checkpoint,
    )
    checkpoint.finish(report)
    saved = _read(checkpoint)
    assert saved["evaluation_run"]["status"] == "completed"
    assert saved["evaluation_run"]["terminal_count"] == 3
    assert saved["evaluation_run"]["failure_count"] == 1
    assert saved["evaluation_run"]["unresolved_case_ids"] == []
    assert "transport exhausted" in saved["report"]["failures"][0]["error_message"]


def test_all_failed_results_are_retained(tmp_path):
    data_set = _data_set()
    checkpoint = _checkpoint(tmp_path, data_set)

    def task(_):
        raise ValueError("failed")

    report = run_data_set(
        data_set,
        task=task,
        evaluators=(),
        case_lifecycle=CaseLifecycle,
        checkpoint=checkpoint,
    )
    checkpoint.finish(report)
    saved = _read(checkpoint)
    assert saved["report"]["cases"] == []
    assert len(saved["report"]["failures"]) == 3
    assert saved["evaluation_run"]["status"] == "completed"


def test_concurrent_completions_keep_each_case_once_and_task_hooks(tmp_path):
    import asyncio

    data_set = _data_set(12)
    checkpoint = _checkpoint(tmp_path, data_set)

    class Enrichment(CaseLifecycle):
        async def prepare_context(self, ctx):
            ctx.attributes["enriched"] = True
            return ctx

        async def teardown(self, result):
            await asyncio.sleep(0)
            if result is not None:
                result.attributes["cleanup"] = True

    report = run_data_set(
        data_set,
        task=lambda value: value,
        evaluators=(),
        max_concurrency=6,
        case_lifecycle=Enrichment,
        checkpoint=checkpoint,
    )
    checkpoint.finish(report)
    saved = _read(checkpoint)
    assert saved["evaluation_run"]["terminal_count"] == 12
    assert len({case["name"] for case in saved["report"]["cases"]}) == 12
    assert all(
        case["attributes"] == {"enriched": True, "cleanup": True}
        for case in saved["report"]["cases"]
    )


def test_case_evaluator_errors_survive_progressive_and_final_write(tmp_path):
    class BrokenJudge(Evaluator):
        def evaluate(self, ctx: EvaluatorContext):
            raise RuntimeError("judge failed")

    data_set = _data_set(1)
    checkpoint = _checkpoint(tmp_path, data_set)
    report = run_data_set(
        data_set,
        task=lambda value: value,
        evaluators=(BrokenJudge(),),
        case_lifecycle=CaseLifecycle,
        checkpoint=checkpoint,
    )
    assert _read(checkpoint)["report"]["cases"][0]["evaluator_failures"]
    checkpoint.finish(report)
    assert (
        "judge failed"
        in _read(checkpoint)["report"]["cases"][0]["evaluator_failures"][0][
            "error_message"
        ]
    )


def test_atomic_replacement_failure_keeps_previous_json_and_cleans_temporary(
    tmp_path, monkeypatch
):
    path = tmp_path / "report.json"
    atomic_write_document(path, {"terminal_count": 1})

    def fail_replace(*_):
        raise OSError("disk failure")

    monkeypatch.setattr("knowledge_map.evaluation.report_file.os.replace", fail_replace)
    with pytest.raises(OSError, match="disk failure"):
        atomic_write_document(path, {"terminal_count": 2})
    assert json.loads(path.read_text()) == {"terminal_count": 1}
    assert list(tmp_path.iterdir()) == [path]


def test_report_membership_mismatch_cannot_be_marked_completed(tmp_path):
    checkpoint = _checkpoint(tmp_path, _data_set())
    with pytest.raises(ValueError, match="selected case population"):
        checkpoint.finish(EvaluationReport(name="test", cases=[]))
    saved = _read(checkpoint)
    assert saved["evaluation_run"]["status"] == "incomplete"
    assert saved["evaluation_run"]["unresolved_case_ids"] == [
        "case-0",
        "case-1",
        "case-2",
    ]


def test_cli_interruption_retains_prior_results_and_unresolved_population(
    tmp_path, monkeypatch
):
    data_set = _data_set()
    source = tmp_path / "data.yaml"
    source.write_text("placeholder")
    monkeypatch.chdir(tmp_path)
    task = SimpleNamespace(
        name="test",
        label_quality=LabelQuality.GOLD,
        headline=RELEVANCE_HEADLINE,
        input_type=int,
        output_type=int,
        metadata_type=dict,
        prompt_digests=dict,
        evaluators=(),
        build=lambda *_: lambda value: value,
    )
    monkeypatch.setattr(evaluate, "task_named", lambda _: task)
    monkeypatch.setattr(evaluate, "load_data_set", lambda *a, **k: data_set)
    monkeypatch.setattr(
        evaluate,
        "select_deployment",
        lambda *a, **k: ModelDeployment(kind=DeploymentKind.LOCAL, model="test"),
    )
    observed_paths = []

    def interrupted(*args, checkpoint, **kwargs):
        assert checkpoint.path.exists()
        checkpoint.started("case-0")
        checkpoint.terminal(
            ReportCase(
                name="case-0",
                inputs=0,
                metadata=None,
                expected_output=0,
                output=0,
                metrics={},
                attributes={},
                scores={},
                labels={},
                assertions={},
                task_duration=0,
                total_duration=0,
            )
        )
        checkpoint.started("case-1")
        raise KeyboardInterrupt("operator interruption")

    monkeypatch.setattr(evaluate, "run_data_set", interrupted)
    args = argparse.Namespace(
        task="test",
        data_set=source,
        deployment="local",
        model="test",
        split=None,
        case_ids=None,
        max_concurrency=1,
        no_report=False,
        report_written_callback=observed_paths.append,
    )
    with pytest.raises(KeyboardInterrupt):
        evaluate._run(args)
    assert len(observed_paths) == 1
    saved = json.loads(observed_paths[0].read_text())
    assert saved["evaluation_run"]["status"] == "incomplete"
    assert saved["evaluation_run"]["terminal_count"] == 1
    assert saved["evaluation_run"]["started_count"] == 2
    assert saved["evaluation_run"]["unresolved_case_ids"] == ["case-1", "case-2"]
    assert "KeyboardInterrupt" in saved["evaluation_run"]["interruption_reason"]


def test_serialization_failure_keeps_prior_snapshot(tmp_path):
    path = tmp_path / "report.json"
    atomic_write_document(path, {"status": "running"})
    circular = {}
    circular["self"] = circular
    with pytest.raises(ValueError, match="Circular reference"):
        atomic_write_document(path, circular)
    assert json.loads(path.read_text()) == {"status": "running"}
    assert list(tmp_path.iterdir()) == [path]


def test_checkpoint_projection_cannot_mutate_framework_result(tmp_path, monkeypatch):
    data_set = _data_set(1).model_copy(update={"task": "retrieval"})
    checkpoint = _checkpoint(tmp_path, data_set)

    def projection(document):
        for case in document["report"]["cases"]:
            case["output"]["retained"].clear()
        return document

    monkeypatch.setattr(
        "knowledge_map.evaluation.retrieval_report.compact_retrieval_report", projection
    )
    report = run_data_set(
        data_set,
        task=lambda _: {"retained": ["original"]},
        evaluators=(),
        case_lifecycle=CaseLifecycle,
        checkpoint=checkpoint,
    )
    assert report.cases[0].output == {"retained": ["original"]}
    checkpoint.finish(report)
    assert report.cases[0].output == {"retained": ["original"]}
    assert _read(checkpoint)["report"]["cases"][0]["output"] == {"retained": []}


def test_report_evaluator_errors_are_preserved_in_final_snapshot(tmp_path):
    from pydantic_evals.evaluators import ReportEvaluator

    class BrokenReportJudge(ReportEvaluator):
        def evaluate(self, ctx):
            raise RuntimeError("report judge failed")

    data_set = _data_set(1)
    checkpoint = _checkpoint(tmp_path, data_set)
    report = run_data_set(
        data_set,
        task=lambda value: value,
        evaluators=(),
        report_evaluators=(BrokenReportJudge(),),
        case_lifecycle=CaseLifecycle,
        checkpoint=checkpoint,
    )
    checkpoint.finish(report)
    assert (
        "report judge failed"
        in _read(checkpoint)["report"]["report_evaluator_failures"][0]["error_message"]
    )


def test_failed_cleanup_still_leaves_terminal_case_snapshot(tmp_path):
    data_set = _data_set(1)
    checkpoint = _checkpoint(tmp_path, data_set)

    class FailedCleanup(CaseLifecycle):
        async def teardown(self, result):
            assert _read(checkpoint)["evaluation_run"]["terminal_count"] == 1
            raise RuntimeError("cleanup failed")

    with pytest.raises(ExceptionGroup, match="unhandled errors"):
        run_data_set(
            data_set,
            task=lambda value: value,
            evaluators=(),
            case_lifecycle=FailedCleanup,
            checkpoint=checkpoint,
        )
    # The CLI converts a returned execution exception to an incomplete marker.
    checkpoint.interrupted("cleanup failed")
    saved = _read(checkpoint)
    assert saved["evaluation_run"]["status"] == "incomplete"
    assert saved["evaluation_run"]["terminal_count"] == 1
    assert saved["report"]["cases"][0]["output"] == 0


def test_checkpoint_failure_still_runs_task_cleanup(tmp_path, monkeypatch):
    data_set = _data_set(1)
    checkpoint = _checkpoint(tmp_path, data_set)
    cleaned = []

    class Cleanup(CaseLifecycle):
        async def teardown(self, result):
            cleaned.append(self.case.name)

    def failed_checkpoint(result):
        raise OSError("checkpoint disk full")

    monkeypatch.setattr(checkpoint, "terminal", failed_checkpoint)
    with pytest.raises(ExceptionGroup, match="unhandled errors"):
        run_data_set(
            data_set,
            task=lambda value: value,
            evaluators=(),
            case_lifecycle=Cleanup,
            checkpoint=checkpoint,
        )
    assert cleaned == ["case-0"]
