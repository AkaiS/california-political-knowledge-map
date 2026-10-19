"""Established populations, explicit subsets, and failed-attempt summaries."""

import copy
import importlib.util
import json
from pathlib import Path

import pytest
import yaml

SCRIPT = Path(__file__).parents[1] / "scripts" / "run_evaluation.py"
spec = importlib.util.spec_from_file_location("run_evaluation_script", SCRIPT)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
ROOT = SCRIPT.parents[1]


def test_default_rag_is_all_authored_cases():
    plan = runner.resolve_plan("rag", root=ROOT)
    authored = yaml.safe_load((ROOT / runner.REFERENCE_DIR / "cases.yaml").read_text())
    assert plan["task"] == "retrieval"
    assert plan["deployment"] == "local"
    assert plan["selection"]["case_ids"] == [case["id"] for case in authored["cases"]]
    assert plan["selection"]["authored_count"] == 25
    assert plan["selection"]["scope"] == "full"


def test_chat_uses_complete_established_set():
    plan = runner.resolve_plan("chat", root=ROOT)
    document = yaml.safe_load((ROOT / "evals/unlabeled/chat.yaml").read_text())
    assert plan["selection"]["case_ids"] == [case["id"] for case in document["cases"]]
    assert plan["selection"]["scope"] == "full"


def test_samples_are_reproducible_and_named_cases_are_exact():
    first = runner.resolve_plan("rag", root=ROOT, sample=5, seed=19)
    second = runner.resolve_plan("rag", root=ROOT, sample=5, seed=19)
    assert first == second
    assert len(first["selection"]["case_ids"]) == 5
    assert first["selection"]["scope"] == "subset"
    assert first["selection"]["seed"] == 19
    selected = runner.resolve_plan("rag", root=ROOT, case_ids=["C-M1-01"])
    assert selected["selection"]["case_ids"] == ["C-M1-01"]
    assert (
        len(runner.resolve_plan("rag", root=ROOT, sample=1)["selection"]["case_ids"])
        == 1
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"sample": 0},
        {"sample": 26},
        {"case_ids": ["unknown"]},
        {"case_ids": ["C-M1-01", "C-M1-01"]},
        {"sample": 1, "case_ids": ["C-M1-01"]},
    ],
)
def test_invalid_selection_fails_before_execution(kwargs):
    with pytest.raises(ValueError):
        runner.resolve_plan("rag", root=ROOT, **kwargs)


def test_replaced_benchmark_and_stale_reference_rejected(tmp_path):
    for source in (
        Path("evals/silver/retrieval.yaml"),
        runner.REFERENCE_DIR / "cases.yaml",
        runner.REFERENCE_DIR / "verified-results.json",
    ):
        destination = tmp_path / source
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((ROOT / source).read_bytes())
    path = tmp_path / "evals/silver/retrieval.yaml"
    document = yaml.safe_load(path.read_text())
    original = copy.deepcopy(document)
    document["cases"][0]["id"] = "replacement"
    path.write_text(yaml.safe_dump(document))
    with pytest.raises(ValueError, match="established authored"):
        runner.resolve_plan("rag", root=tmp_path)
    original["cases"][0]["metadata"]["reference_sha256"] = "stale"
    path.write_text(yaml.safe_dump(original))
    with pytest.raises(ValueError, match="checksum"):
        runner.resolve_plan("rag", root=tmp_path)


def _saved(tmp_path, document):
    path = tmp_path / document["task"] / "run.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document))
    return path


def test_report_prints_the_scorecard_and_exits_with_its_exit_code(tmp_path, capsys):
    from knowledge_map.evaluation.run_report import ReportDocument, Scorecard

    document = {
        "task": "chat",
        "label_quality": "unlabeled",
        "report": {
            "cases": [
                {"name": "decline", "output": {"preparation": {"status": "declined"}}}
            ],
            "failures": [{"name": "framework", "error_message": "exhausted"}],
        },
    }
    path = _saved(tmp_path, document)
    other = _saved(tmp_path, {"task": "relevance", "report": {"cases": []}})
    expected = Scorecard.build([ReportDocument.load(path)], baseline="auto")
    both = Scorecard.build(
        [ReportDocument.load(path), ReportDocument.load(other)], baseline="auto"
    )

    code = runner.main(["--report", str(path)])

    assert json.loads(capsys.readouterr().out) == json.loads(
        json.dumps(expected.to_json())
    )
    assert code == expected.exit_code == 1

    code = runner.main(
        ["--format", "markdown", "--report", str(path), "--report", str(other)]
    )

    assert capsys.readouterr().out == both.to_markdown()
    assert code == both.exit_code == 1


def test_execute_uses_engine_cli_and_reports_saved_failure(tmp_path, monkeypatch):
    plan = runner.resolve_plan("rag", root=ROOT, sample=1)
    selected = plan["selection"]["case_ids"]
    document = {
        "task": "retrieval",
        "report": {"cases": [], "failures": [{"name": selected[0]}]},
        "evaluation_run": {"status": "completed", "selected_case_ids": selected},
    }
    report_path = _saved(tmp_path, document)

    def run(args):
        assert args.case_ids == selected
        assert args.no_report is False
        assert args.run_metadata["selection"] == plan["selection"]
        args.report_written_callback(report_path)
        raise SystemExit("saved framework failure")

    monkeypatch.setattr(runner.evaluate, "_run", run)
    scorecard, code = runner.execute_plan(plan)
    summary = scorecard.to_json()
    assert code == 1
    assert summary["counts"]["terminal"] == 1
    assert summary["counts"]["execution_failures"] == 1


def test_plan_mode_never_executes_models(monkeypatch, capsys):
    monkeypatch.chdir(ROOT)
    monkeypatch.setattr(
        runner, "execute_plan", lambda plan: pytest.fail("execution in plan mode")
    )
    assert runner.main(["rag", "--plan"]) == 0
    assert (
        json.loads(capsys.readouterr().out)["evaluation_plan"]["selection"][
            "authored_count"
        ]
        == 25
    )


def test_plan_drift_is_rejected_before_execution(monkeypatch):
    plan = runner.resolve_plan("rag", root=ROOT)
    plan["prompts"] = {"changed": "digest"}
    monkeypatch.setattr(
        runner.evaluate, "_run", lambda args: pytest.fail("executed drifted plan")
    )
    with pytest.raises(ValueError, match="changed after planning"):
        runner.execute_plan(plan)


def test_script_cli_checkpoint_integration_without_model_calls(tmp_path, monkeypatch):
    from dataclasses import replace

    from pydantic_evals.lifecycle import CaseLifecycle

    from knowledge_map.evaluation import engine

    task = runner.task_named("relevance")
    fake = replace(
        task,
        build=lambda deployment, dataset: (
            lambda case_input: task.output_type(classification="RELEVANT")
        ),
        evaluators=(),
        prompts=lambda: {"test": "fixed"},
        case_lifecycle=CaseLifecycle,
    )
    monkeypatch.setattr(runner, "task_named", lambda name: fake)
    monkeypatch.setattr(runner.evaluate, "task_named", lambda name: fake)
    monkeypatch.setattr(engine, "setup_telemetry", lambda: None)
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "evals/gold/relevance.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(
        yaml.safe_dump(
            {
                "task": "relevance",
                "description": "integration",
                "cases": [
                    {
                        "id": "case",
                        "description": "case",
                        "task_input": {
                            "headline": "Headline",
                            "url": "https://example.test/article",
                        },
                        "expected_output": {"classification": "RELEVANT"},
                    }
                ],
            }
        )
    )
    plan = runner.resolve_plan("relevance")
    scorecard, code = runner.execute_plan(plan)
    summary = scorecard.to_json()
    assert code == 0
    assert summary["status"] == "completed"
    assert summary["scope"] == "full"
    assert summary["counts"]["selected"] == summary["counts"]["terminal"] == 1
    saved = json.loads(Path(summary["report_path"]).read_text())
    assert saved["experiment_metadata"]["selection"] == plan["selection"]
    assert saved["data_set_sha256"] == plan["data_set_sha256"]
    assert saved["experiment_metadata"]["headline_version"] == "relevance-v1"
    assert summary["headline"]["rows"][0]["metric"] == "relevant_f1"


def test_plan_records_a_custom_reviewer_port():
    assert (
        runner.resolve_plan("rag", root=ROOT, reviewer_port=8777)["reviewer_port"]
        == 8777
    )
