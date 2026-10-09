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


def _document():
    return {
        "task": "retrieval",
        "label_quality": "silver",
        "experiment_metadata": {"selection": {"scope": "full", "seed": None}},
        "evaluation_run": {
            "status": "incomplete",
            "selected_case_ids": [
                "answer",
                "guidance_failure",
                "framework_failure",
                "pending",
            ],
            "started_case_ids": ["answer", "guidance_failure", "framework_failure"],
            "selected_cases": [],
        },
        "report": {
            "cases": [
                {
                    "name": "answer",
                    "output": {
                        "answer": {"introduction": None, "source_notes": []},
                        "rendered_text": "Answer",
                        "result": {
                            "execution": {
                                "outcomes": [{"branch": "dense", "status": "succeeded"}]
                            }
                        },
                    },
                    "scores": {"fused_recall_at_10": {"value": 0.8}},
                },
                {
                    "name": "guidance_failure",
                    "output": {"failure": {"stage": "retrieval_and_guidance"}},
                    "scores": {"fused_recall_at_10": {"value": 0.0}},
                },
            ],
            "failures": [{"name": "framework_failure", "error_message": "exhausted"}],
        },
    }


def _saved(tmp_path, document):
    path = tmp_path / document["task"] / "run.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document))
    return path


def test_summary_retains_failures_and_unresolved_denominators(tmp_path):
    summary = runner.summarize_report(_saved(tmp_path, _document()))
    assert summary["counts"] == {
        "selected": 4,
        "attempted": 3,
        "terminal": 3,
        "completed_answers": 1,
        "declined": 0,
        "execution_failures": 2,
        "unresolved": 1,
        "evaluator_errors": 0,
    }
    assert summary["unresolved_case_ids"] == ["pending"]
    assert summary["failures_by_stage"] == {"framework": 1, "retrieval_and_guidance": 1}
    assert summary["metrics"]["fused_recall_at_10"]["mean"] == 0.4
    assert summary["metrics"]["fused_recall_at_10"]["scored_cases"] == 2
    assert summary["metrics"]["fused_recall_at_10"]["missing_cases"] == 2
    assert summary["branch_completion"]["dense"]["unrecorded"] == 3
    assert summary["metrics"]["fused_ndcg_at_10"]["unavailable_reason"]
    assert summary["reviewer_url"] == "http://127.0.0.1:8766/runs/retrieval--run"


def test_report_cli_counts_direct_and_historical_declines_without_rewriting_report(
    tmp_path, capsys
):
    document = {
        "task": "chat",
        "label_quality": "unlabeled",
        "report": {
            "cases": [
                {
                    "name": "historical-decline",
                    "output": {
                        "preparation": {
                            "status": "declined",
                            "message": "Forecasts are outside the question policy.",
                        }
                    },
                },
                {
                    "name": "direct-decline",
                    "output": {
                        "approval_mode": "direct_question",
                        "preparation": None,
                        "assessment": {
                            "status": "declined",
                            "explanation": "Forecasts are outside the question policy.",
                        },
                    },
                },
                {
                    "name": "needs-edit",
                    "output": {
                        "assessment": {
                            "status": "needs_edit",
                            "explanation": "Name the bill in the complete question.",
                        }
                    },
                },
                {
                    "name": "deferred-with-guidance",
                    "output": {
                        "assessment": {
                            "status": "deferred",
                            "explanation": "The collection has a limited date range.",
                            "recoverable_portion": "Reporting inside that range.",
                        },
                        "answer": {"introduction": None, "source_notes": []},
                        "rendered_text": "Read the available reporting.",
                    },
                },
            ]
        },
    }
    path = _saved(tmp_path, document)
    original = path.read_bytes()

    assert runner.main(["--report", str(path)]) == 0
    summary = json.loads(capsys.readouterr().out)

    assert summary["counts"]["selected"] == summary["counts"]["terminal"] == 4
    assert summary["counts"]["declined"] == 2
    assert summary["counts"]["completed_answers"] == 1
    assert summary["counts"]["execution_failures"] == 0
    assert summary["counts"]["unresolved"] == 0
    assert path.read_bytes() == original


def test_summary_detects_duplicate_unexpected_and_mismatched_ids(tmp_path):
    document = _document()
    document["report"]["cases"].append(document["report"]["cases"][0])
    document["report"]["failures"].append({"name": "surprise"})
    summary = runner.summarize_report(
        _saved(tmp_path, document), expected_ids=["answer"]
    )
    assert summary["status"] == "incomplete"
    assert summary["integrity"]["duplicate_case_ids"] == ["answer"]
    assert summary["integrity"]["selection_manifest_mismatch"]
    assert "surprise" in summary["integrity"]["unexpected_case_ids"]


def test_unlabeled_and_historical_reports_are_explicit(tmp_path):
    document = {
        "task": "chat",
        "label_quality": "unlabeled",
        "report": {
            "cases": [
                {"name": "decline", "output": {"preparation": {"status": "declined"}}}
            ]
        },
    }
    summary = runner.summarize_report(_saved(tmp_path, document))
    assert summary["scope"] == "unknown"
    assert summary["status"] == "historical_selection_unknown"
    assert summary["counts"]["declined"] == 1
    assert (
        summary["metrics_unavailable_reason"]
        == "This Data Set has no reference judgments."
    )


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
    summary, code = runner.execute_plan(plan)
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


@pytest.mark.parametrize("output", [True, False, "relevant", 3, ["topic"]])
def test_component_scalar_output_is_reviewably_summarized(tmp_path, output):
    document = {
        "task": "relevance",
        "report": {
            "cases": [
                {
                    "name": "component",
                    "output": output,
                    "scores": {"correct": {"value": 1.0}},
                }
            ]
        },
    }
    summary = runner.summarize_report(_saved(tmp_path, document))
    assert summary["counts"]["terminal"] == 1
    assert summary["metrics"]["correct"]["mean"] == 1.0
    assert summary["branch_completion"] == {}


def test_historical_chat_answers_and_branches_use_real_schema():
    path = (
        ROOT
        / "evals/reports/chat/20261007T201147Z-35d1475-local-gemma4-26b-1499ceec2201.json"
    )
    summary = runner.summarize_report(path)
    assert summary["counts"]["completed_answers"] == 2
    assert summary["branch_completion"]["dense"]["succeeded"] == 2
    assert summary["branch_completion"]["dense"]["unrecorded"] == 0
    assert summary["provenance"]["experiment_metadata"]["prompts"]


def test_historical_rag_metrics_match_reviewer_projection():
    path = (
        ROOT
        / "evals/reports/retrieval/20261002T233848Z-e237389-local-gemma4-26b-1499ceec2201.json"
    )
    document = json.loads(path.read_text())
    from knowledge_map.evaluation.rag_review import project_report

    projection = project_report(document)
    summary = runner.summarize_report(path)
    for metric in ("precision", "two_hop_recall", "recall"):
        row = next(
            row
            for row in projection["metrics"]
            if row["branch"] == "fused" and row["metric"] == metric and row["k"] == 10
        )
        reported = summary["metrics"][f"fused_{metric}_at_10"]
        assert reported["mean"] == row["value"]
        assert reported["scored_cases"] == row["scored_cases"]
        assert reported["applicable_cases"] == row["applicable_cases"]


def test_component_caught_failures_and_boolean_evaluators_are_retained(tmp_path):
    document = {
        "task": "coreference",
        "report": {
            "cases": [
                {
                    "name": "failed",
                    "output": {"failure_type": "task_exhaustion"},
                    "assertions": {"Completed": {"value": False}},
                },
                {
                    "name": "success",
                    "output": {},
                    "assertions": {"Completed": {"value": True}},
                },
            ]
        },
    }
    summary = runner.summarize_report(_saved(tmp_path, document))
    assert summary["counts"]["execution_failures"] == 1
    assert summary["failures_by_stage"] == {"task:task_exhaustion": 1}
    assert summary["assertions"]["Completed"]["pass_rate"] == 0.5
    assert summary["assertions"]["Completed"]["failed"] == 1


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
            lambda case_input: {"classification": "RELEVANT"}
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
    summary, code = runner.execute_plan(plan)
    assert code == 0
    assert summary["status"] == "completed"
    assert summary["scope"] == "full"
    assert summary["counts"]["selected"] == summary["counts"]["terminal"] == 1
    saved = json.loads(Path(summary["report_path"]).read_text())
    assert saved["experiment_metadata"]["selection"] == plan["selection"]
    assert saved["data_set_sha256"] == plan["data_set_sha256"]


def test_reviewer_command_routes_exact_root_and_custom_port(tmp_path):
    import shlex

    path = _saved(tmp_path, _document())
    summary = runner.summarize_report(path, reviewer_port=8777)
    assert summary["reviewer_url"] == "http://127.0.0.1:8777/runs/retrieval--run"
    argv = shlex.split(summary["reviewer_command"])
    assert argv[argv.index("--reports-dir") + 1] == str(tmp_path.resolve())
    assert argv[argv.index("--port") + 1] == "8777"
    assert "unverified" in summary["reviewer_status"]
    assert (
        runner.resolve_plan("rag", root=ROOT, reviewer_port=8777)["reviewer_port"]
        == 8777
    )
    with pytest.raises(ValueError, match="Reviewer port"):
        runner.summarize_report(path, reviewer_port=0)


def test_standalone_report_has_no_misleading_reviewer_link(tmp_path):
    path = tmp_path / "standalone.json"
    path.write_text(json.dumps(_document()))
    summary = runner.summarize_report(path)
    assert summary["reviewer_url"] is None
    assert summary["reviewer_command"] is None
    assert "TASK/*.json" in summary["reviewer_status"]
