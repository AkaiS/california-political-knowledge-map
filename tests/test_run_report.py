"""Scorecards summarize saved Evaluation Reports.

Every test loads saved report documents with ``ReportDocument.load``, builds a
``Scorecard`` and reads only its JSON and exit code.
"""

from __future__ import annotations

import json
import shlex
from pathlib import Path

import pytest
from chat_runs import (
    FRAMEWORK_FAILURE,
    STAGE_FAILURE,
    answered,
    assessed,
    declined_in_preparation,
    run_chat,
)
from relevance_runs import CONFUSION_CASES, RELEVANT, run_relevance
from retrieval_runs import POPULATION, run_retrieval

from knowledge_map.evaluation.run_report import ReportDocument, Scorecard

ROOT = Path(__file__).parents[1]


def scorecard(path, **options):
    return Scorecard.build([ReportDocument.load(path)], baseline="none", **options)


def _saved(tmp_path, document):
    path = tmp_path / document["task"] / "run.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document))
    return path


def test_completed_run_summarizes_its_recorded_headline(tmp_path):
    card = scorecard(run_relevance(tmp_path, CONFUSION_CASES))
    summary = card.to_json()

    assert card.exit_code == 0
    assert summary["status"] == "completed"
    assert summary["counts"]["selected"] == summary["counts"]["terminal"] == 5
    assert summary["provenance"]["headline_version"] == "relevance-v1"
    headline = summary["headline"]
    assert headline["version"] == "relevance-v1"
    assert headline["no_headline_reason"] is None
    assert headline["rows"][0] == {
        "metric": "relevant_f1",
        "role": "primary",
        "aggregation": "pooled",
        "value": 4 / 6,
        "numerator": 4.0,
        "denominator": 6.0,
        "scored_cases": 5,
        "selected_cases": 5,
        "unavailable_reason": None,
    }
    assert [row["metric"] for row in headline["rows"]] == [
        "relevant_f1",
        "relevant_precision",
        "relevant_recall",
        "accuracy",
        "true_positives",
        "false_positives",
        "false_negatives",
        "true_negatives",
        "execution_failure_rate",
    ]


def test_completed_run_with_a_failed_case_keeps_its_headline_and_exits_nonzero(
    tmp_path,
):
    card = scorecard(
        run_relevance(
            tmp_path, [*CONFUSION_CASES, ("raised", RELEVANT, RuntimeError("down"))]
        )
    )
    summary = card.to_json()

    assert card.exit_code == 1
    assert summary["counts"]["execution_failures"] == 1
    rows = {row["metric"]: row for row in summary["headline"]["rows"]}
    assert rows["execution_failure_rate"]["value"] == 1 / 6
    assert rows["relevant_f1"]["scored_cases"] == 5


def test_failed_headline_evaluator_summarizes_as_headline_evaluator_failed(tmp_path):
    card = scorecard(
        run_relevance(tmp_path, [*CONFUSION_CASES, ("unreadable", RELEVANT, None)])
    )
    summary = card.to_json()

    assert summary["status"] == "completed"
    assert summary["headline"] == {
        "version": "relevance-v1",
        "no_headline_reason": "headline_evaluator_failed",
        "rows": [],
    }
    assert summary["counts"]["evaluator_errors"] >= 1
    assert summary["counts"]["completed_answers"] is None
    assert card.exit_code == 1


def test_interrupted_run_summarizes_as_incomplete_run_with_its_population(tmp_path):
    card = scorecard(
        run_relevance(
            tmp_path,
            [
                ("first", RELEVANT, RELEVANT),
                ("interrupted", RELEVANT, KeyboardInterrupt("operator")),
                ("never-started", RELEVANT, RELEVANT),
            ],
        )
    )
    summary = card.to_json()

    assert summary["status"] == "incomplete"
    assert summary["headline"]["no_headline_reason"] == "incomplete_run"
    assert summary["headline"]["rows"] == []
    assert summary["counts"]["selected"] == 3
    assert summary["counts"]["unresolved"] >= 1
    assert card.exit_code == 1


def test_report_from_before_headlines_summarizes_as_predating_them():
    path = ROOT / "evals/reports/relevance/20260820T002619Z-cf12c89-gemma4-26b.json"
    summary = scorecard(path).to_json()

    assert summary["status"] == "historical_selection_unknown"
    assert summary["headline"] == {
        "version": None,
        "no_headline_reason": "predates_headline_metrics",
        "rows": [],
    }
    assert summary["counts"]["selected"] == summary["counts"]["terminal"] == 74


def test_unreadable_file_is_not_a_report(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("[1, 2]")
    with pytest.raises(ValueError, match="not an Evaluation Report"):
        ReportDocument.load(path)


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


def test_summary_retains_failures_and_unresolved_denominators(tmp_path):
    card = scorecard(_saved(tmp_path, _document()))
    summary = card.to_json()
    assert summary["counts"] == {
        "selected": 4,
        "attempted": 3,
        "terminal": 3,
        "scored": 1,
        "completed_answers": None,
        "declined": None,
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
    assert card.exit_code == 1


def test_chat_answers_and_declines_are_counted_from_the_recorded_headline(tmp_path):
    path = run_chat(
        tmp_path,
        [
            answered("AB 1"),
            answered("AB 2", introduction=None),
            assessed("SB 1", "declined"),
            declined_in_preparation("SB 2"),
            assessed("SB 3", "deferred", recoverable_portion="Reporting since 2024."),
            assessed("SB 4", "needs_edit"),
            STAGE_FAILURE,
            FRAMEWORK_FAILURE,
        ],
    )
    original = path.read_bytes()

    card = scorecard(path)
    summary = card.to_json()

    assert summary["headline"]["version"] == "chat-v1"
    assert summary["counts"]["selected"] == summary["counts"]["terminal"] == 8
    assert summary["counts"]["completed_answers"] == 2
    assert summary["counts"]["declined"] == 2
    assert summary["counts"]["execution_failures"] == 2
    assert card.exit_code == 1
    assert path.read_bytes() == original

    # Outputs that no longer show any answer or decline leave the counts as
    # the recorded table states them.
    document = json.loads(original)
    for case in document["report"]["cases"]:
        case["output"] = {"question": case["output"]["question"]}
    rewritten = tmp_path / "rewritten" / "run.json"
    rewritten.parent.mkdir()
    rewritten.write_text(json.dumps(document))
    counts = scorecard(rewritten).to_json()["counts"]
    assert (counts["completed_answers"], counts["declined"]) == (2, 2)


def test_retrieval_completed_answers_are_counted_from_the_recorded_headline(
    tmp_path,
):
    # One question was answered; two ended at a failed Evidence Assembly.
    card = scorecard(run_retrieval(tmp_path, POPULATION))
    summary = card.to_json()

    assert summary["headline"]["version"] == "retrieval-v1"
    assert summary["counts"]["completed_answers"] == 1
    assert summary["counts"]["execution_failures"] == 0
    assert card.exit_code == 0


def test_summary_detects_duplicate_and_unexpected_ids(tmp_path):
    document = _document()
    document["report"]["cases"].append(document["report"]["cases"][0])
    document["report"]["failures"].append({"name": "surprise"})
    card = scorecard(_saved(tmp_path, document))
    summary = card.to_json()
    assert summary["status"] == "incomplete"
    assert summary["integrity"]["duplicate_case_ids"] == ["answer"]
    assert summary["integrity"]["unexpected_case_ids"] == ["surprise"]
    assert summary["integrity"]["selection_manifest_mismatch"] is False
    assert card.exit_code == 1


def test_recorded_selection_that_disagrees_with_the_run_is_a_mismatch(tmp_path):
    document = _document()
    document["evaluation_run"]["status"] = "completed"
    document["experiment_metadata"]["selection"]["case_ids"] = [
        "answer",
        "planned-only",
    ]
    card = scorecard(_saved(tmp_path, document))
    summary = card.to_json()

    assert summary["status"] == "incomplete"
    assert summary["integrity"] == {
        "unexpected_case_ids": ["framework_failure", "guidance_failure"],
        "duplicate_case_ids": [],
        "selection_manifest_mismatch": True,
    }
    assert summary["case_ids"] == ["answer", "planned-only"]
    assert summary["unresolved_case_ids"] == ["planned-only"]
    assert summary["counts"]["selected"] == 2
    assert summary["counts"]["unresolved"] == 1
    assert card.exit_code == 1


def test_recorded_selection_that_matches_the_run_is_not_a_mismatch(tmp_path):
    document = _document()
    document["experiment_metadata"]["selection"]["case_ids"] = list(
        document["evaluation_run"]["selected_case_ids"]
    )
    summary = scorecard(_saved(tmp_path, document)).to_json()

    assert summary["integrity"]["selection_manifest_mismatch"] is False
    assert summary["unresolved_case_ids"] == ["pending"]


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
    summary = scorecard(_saved(tmp_path, document)).to_json()
    assert summary["scope"] == "unknown"
    assert summary["status"] == "historical_selection_unknown"
    # Answers and declines are counted only by a recorded headline table.
    assert summary["headline"]["no_headline_reason"] == "predates_headline_metrics"
    assert summary["counts"]["declined"] is None
    assert summary["counts"]["completed_answers"] is None
    assert (
        summary["metrics_unavailable_reason"]
        == "This Data Set has no reference judgments."
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
    summary = scorecard(_saved(tmp_path, document)).to_json()
    assert summary["counts"]["terminal"] == 1
    assert summary["metrics"]["correct"]["mean"] == 1.0
    assert summary["branch_completion"] == {}


def test_historical_chat_answers_and_branches_use_real_schema():
    path = (
        ROOT
        / "evals/reports/chat/20261007T201147Z-35d1475-local-gemma4-26b-1499ceec2201.json"
    )
    summary = scorecard(path).to_json()
    assert summary["counts"]["completed_answers"] is None
    assert summary["branch_completion"]["dense"]["succeeded"] == 2
    assert summary["branch_completion"]["dense"]["unrecorded"] == 0
    assert summary["provenance"]["experiment_metadata"]["prompts"]
    assert summary["headline"]["no_headline_reason"] == "predates_headline_metrics"


def test_historical_rag_diagnostic_metrics_are_recorded_case_score_means():
    path = (
        ROOT
        / "evals/reports/retrieval/20261002T233848Z-e237389-local-gemma4-26b-1499ceec2201.json"
    )
    metrics = scorecard(path).to_json()["metrics"]
    for metric, mean in {
        "precision": 0.256,
        "recall": pytest.approx(0.7042786635619782),
    }.items():
        reported = metrics[f"fused_{metric}_at_10"]
        assert (reported["mean"], reported["scored_cases"]) == (mean, 25)
        assert reported["inclusion_policy"].startswith(
            "Unweighted mean of recorded numeric case scores"
        )
    # Replayed reviewer-only measurements stay in the RAG reviewer.
    assert "fused_two_hop_recall_at_10" not in metrics


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
    card = scorecard(_saved(tmp_path, document))
    summary = card.to_json()
    assert summary["counts"]["execution_failures"] == 1
    assert summary["failures_by_stage"] == {"task:task_exhaustion": 1}
    assert summary["assertions"]["Completed"]["pass_rate"] == 0.5
    assert summary["assertions"]["Completed"]["failed"] == 1
    assert card.exit_code == 1


def test_reviewer_command_routes_exact_root_and_custom_port(tmp_path):
    path = _saved(tmp_path, _document())
    summary = scorecard(path, reviewer_port=8777).to_json()
    assert summary["reviewer_url"] == "http://127.0.0.1:8777/runs/retrieval--run"
    argv = shlex.split(summary["reviewer_command"])
    assert argv[argv.index("--reports-dir") + 1] == str(tmp_path.resolve())
    assert argv[argv.index("--port") + 1] == "8777"
    assert "unverified" in summary["reviewer_status"]
    with pytest.raises(ValueError, match="Reviewer port"):
        scorecard(path, reviewer_port=0)


def test_standalone_report_has_no_misleading_reviewer_link(tmp_path):
    path = tmp_path / "standalone.json"
    path.write_text(json.dumps(_document()))
    summary = scorecard(path).to_json()
    assert summary["reviewer_url"] is None
    assert summary["reviewer_command"] is None
    assert "TASK/*.json" in summary["reviewer_status"]
