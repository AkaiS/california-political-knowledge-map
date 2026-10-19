"""A scorecard renders saved Evaluation Reports as markdown.

Every test saves Evaluation Reports through an engine run, pins the metadata a
run records from its environment (time, commit, worktree state), builds a
``Scorecard`` from ``ReportDocument.load`` and reads only its markdown and
exit code.  Expected text is written out in full; paths and task durations
that differ on every run are replaced by names before comparing.
"""

from __future__ import annotations

import pytest
from chat_runs import STAGE_FAILURE, answered, assessed, run_chat
from engine_runs import run_task
from pinned_reports import markdown, pinned
from relevance_runs import CONFUSION_CASES, IRRELEVANT, RELEVANT, run_relevance

from knowledge_map.evaluation import LabelQuality
from knowledge_map.evaluation.run_report import ReportDocument, Scorecard
from knowledge_map.evaluation.tasks.extraction import (
    ExtractionExpectation,
    ExtractionInput,
    ExtractionOutput,
)


@pytest.fixture(autouse=True)
def disable_telemetry(monkeypatch):
    monkeypatch.setattr("knowledge_map.evaluation.engine.setup_telemetry", lambda: None)


# Nothing predicted RELEVANT, so RELEVANT precision has no denominator.
NOTHING_RELEVANT = [
    (case_id, expected, IRRELEVANT) for case_id, expected, _ in CONFUSION_CASES
]


def test_one_axis_renders_its_headline_against_the_latest_comparable_run(tmp_path):
    baseline = pinned(
        run_relevance(tmp_path, CONFUSION_CASES), ran_at="2026-10-01T12:00:00+00:00"
    )
    current = pinned(
        run_relevance(tmp_path, NOTHING_RELEVANT),
        trace_url="https://example.com/traces/1",
    )

    card = Scorecard.build([ReportDocument.load(current)], baseline="auto")

    assert card.exit_code == 0
    assert markdown(card, current=current, baseline=baseline) == (
        "## relevance: relevant_f1 0.000 (-0.667 against the baseline)\n"
        "\n"
        "Population: label quality gold, selection scope full; "
        "5 selected, 5 scored, 0 failed, 0 unresolved.\n"
        "\n"
        "Baseline: `<baseline>` (comparable).\n"
        "\n"
        "| metric | value | baseline value | change | scored / selected | aggregation |\n"
        "| --- | --- | --- | --- | --- | --- |\n"
        "| relevant_f1 | 0.000 (0/3) | 0.667 (4/6) | -0.667 | 5/5 | pooled |\n"
        "| relevant_precision | unavailable (0/0) | 0.667 (2/3) | unavailable "
        "| 5/5 | pooled |\n"
        "| relevant_recall | 0.000 (0/3) | 0.667 (2/3) | -0.667 | 5/5 | pooled |\n"
        "| accuracy | 0.400 (2/5) | 0.600 (3/5) | -0.200 | 5/5 | rate |\n"
        "| true_positives | 0.000 (0/5) | 0.400 (2/5) | -0.400 | 5/5 | rate |\n"
        "| false_positives | 0.000 (0/5) | 0.200 (1/5) | -0.200 | 5/5 | rate |\n"
        "| false_negatives | 0.600 (3/5) | 0.200 (1/5) | +0.400 | 5/5 | rate |\n"
        "| true_negatives | 0.400 (2/5) | 0.200 (1/5) | +0.200 | 5/5 | rate |\n"
        "| execution_failure_rate | 0.000 (0/5) | 0.000 (0/5) | +0.000 "
        "| 5/5 | rate |\n"
        "\n"
        "- relevant_precision (pooled) is unavailable: "
        "no case contributed to the denominator\n"
        "\n"
        "Provenance: commit 1234567 (clean worktree); Model Deployment local stub; "
        "prompts relevance cdcdcdcdcdcd; Data Set abababababab; "
        "headline relevance-v1; [report](<current>); "
        "[trace](https://example.com/traces/1).\n"
    )


def test_report_without_a_headline_renders_its_population_and_reason(tmp_path):
    current = pinned(
        run_relevance(
            tmp_path,
            [
                ("first", RELEVANT, RELEVANT),
                ("interrupted", RELEVANT, KeyboardInterrupt("operator")),
                ("never-started", RELEVANT, RELEVANT),
            ],
        )
    )

    card = Scorecard.build([ReportDocument.load(current)], baseline="none")

    assert card.exit_code == 1
    assert markdown(card, current=current) == (
        "## relevance: no Headline Metrics\n"
        "\n"
        "Population: label quality gold, selection scope full; "
        "3 selected, 1 scored, 0 failed, 2 unresolved.\n"
        "\n"
        "Baseline: none (not requested).\n"
        "\n"
        "No Headline Metrics: incomplete_run.\n"
        "\n"
        "Provenance: commit 1234567 (clean worktree); Model Deployment local stub; "
        "prompts relevance cdcdcdcdcdcd; Data Set abababababab; "
        "headline relevance-v1; [report](<current>); no trace.\n"
    )


COMPARED = "## relevance: relevant_f1 0.667 (+0.000 against the baseline)"
NOT_COMPARED = "## relevance: relevant_f1 0.667 (no comparable baseline)"


@pytest.mark.parametrize(
    ("baseline_fields", "current_fields", "heading", "baseline_line"),
    [
        (
            {"dirty": True},
            {},
            COMPARED,
            (
                "Baseline: `<baseline>` "
                "(comparable with caveat; dirty worktree on the baseline side)."
            ),
        ),
        (
            {"dirty": True},
            {"dirty": True},
            COMPARED,
            (
                "Baseline: `<baseline>` (comparable with caveat; "
                "dirty worktree on the current and baseline sides)."
            ),
        ),
        (
            {
                "data_set_sha256": "00" * 32,
                "metadata": {"headline_version": "relevance-v0"},
                "dirty": True,
            },
            {},
            NOT_COMPARED,
            (
                "Baseline: `<baseline>` (not comparable; failed data_set_revision, "
                "headline_version; dirty worktree on the baseline side)."
            ),
        ),
    ],
    ids=["dirty-baseline", "both-dirty", "not-comparable"],
)
def test_baseline_line_names_the_comparison_status_and_what_qualifies_it(
    tmp_path, baseline_fields, current_fields, heading, baseline_line
):
    baseline = pinned(
        run_relevance(tmp_path / "baseline", CONFUSION_CASES), **baseline_fields
    )
    current = pinned(
        run_relevance(tmp_path / "current", CONFUSION_CASES), **current_fields
    )

    card = Scorecard.build([ReportDocument.load(current)], baseline=baseline)

    rendered = markdown(card, baseline=baseline).splitlines()
    assert (rendered[0], rendered[4]) == (heading, baseline_line)


def test_without_an_earlier_run_the_baseline_line_says_so(tmp_path):
    current = pinned(run_relevance(tmp_path, CONFUSION_CASES))

    card = Scorecard.build([ReportDocument.load(current)], baseline="auto")

    rendered = card.to_markdown().splitlines()
    assert (rendered[0], rendered[4]) == (
        NOT_COMPARED,
        "Baseline: none (no earlier run).",
    )


def test_an_unavailable_primary_heading_gives_its_reason_not_a_change(tmp_path):
    only_irrelevant = [(case_id, IRRELEVANT, IRRELEVANT) for case_id in ("a", "b")]
    baseline = pinned(
        run_relevance(tmp_path, only_irrelevant), ran_at="2026-10-01T12:00:00+00:00"
    )
    current = pinned(run_relevance(tmp_path, only_irrelevant))

    card = Scorecard.build([ReportDocument.load(current)], baseline="auto")

    rendered = markdown(card, baseline=baseline).splitlines()
    assert (rendered[0], rendered[4]) == (
        (
            "## relevance: relevant_f1 unavailable "
            "(no case contributed to the denominator)"
        ),
        "Baseline: `<baseline>` (comparable).",
    )


def run_extraction(directory):
    # Every diagnostic accuracy needs a matched node; this chunk has none.
    return run_task(
        directory,
        "extraction",
        [
            (
                "chunk",
                ExtractionExpectation(nodes=[], relationships=[]),
                ExtractionOutput(nodes=[], relationships=[]),
            )
        ],
        task_input=lambda case_id: ExtractionInput(
            url=case_id, title=case_id, chunk_index=0, text=case_id
        ),
        label_quality=LabelQuality.SILVER,
    )


def test_diagnostic_rows_render_in_a_collapsed_section_after_the_scorecard(tmp_path):
    current = run_extraction(tmp_path)

    rendered = Scorecard.build(
        [ReportDocument.load(current)], baseline="none"
    ).to_markdown()

    scorecard, collapsed = rendered.split("\n\n<details>\n", 1)
    assert scorecard.splitlines()[-1].startswith("Provenance: ")
    assert "accuracy" not in scorecard
    assert collapsed == (
        "<summary>Diagnostic rows</summary>\n"
        "\n"
        "| metric | value | scored / selected | aggregation |\n"
        "| --- | --- | --- | --- |\n"
        "| sub_label_accuracy | unavailable | 0/1 | per_case_mean |\n"
        "| node_property_accuracy | unavailable | 0/1 | per_case_mean |\n"
        "| claim_property_accuracy | unavailable | 0/1 | per_case_mean |\n"
        "| stance_alignment_accuracy | unavailable | 0/1 | per_case_mean |\n"
        "\n"
        "- sub_label_accuracy (per_case_mean) is unavailable: "
        "no case contributed to the denominator\n"
        "- node_property_accuracy (per_case_mean) is unavailable: "
        "no case contributed to the denominator\n"
        "- claim_property_accuracy (per_case_mean) is unavailable: "
        "no case contributed to the denominator\n"
        "- stance_alignment_accuracy (per_case_mean) is unavailable: "
        "no case contributed to the denominator\n"
        "\n"
        "</details>\n"
    )


def test_an_axis_without_a_headline_gives_its_reason_in_the_summary_row(tmp_path):
    complete = pinned(run_relevance(tmp_path / "complete", CONFUSION_CASES))
    interrupted = pinned(
        run_relevance(
            tmp_path / "interrupted",
            [
                ("first", RELEVANT, RELEVANT),
                ("interrupted", RELEVANT, KeyboardInterrupt("operator")),
            ],
        )
    )

    card = Scorecard.build(
        [ReportDocument.load(path) for path in (complete, interrupted)],
        baseline="none",
    )

    assert card.exit_code == 1
    assert card.to_markdown().split("\n\n", 1)[0] == (
        "| axis | label quality | primary metric | value | change | scored / "
        "selected | failure rate | comparison status |\n"
        "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
        "| relevance | gold | relevant_f1 | 0.667 (4/6) | - | 5/5 | 0.000 (0/5) "
        "| not requested |\n"
        "| relevance | gold | - | no Headline Metrics (incomplete_run) | - | 1/2 "
        "| - | not requested |"
    )


def test_several_axes_open_with_one_row_per_axis_then_each_scorecard(tmp_path):
    baseline = pinned(
        run_relevance(tmp_path / "relevance", CONFUSION_CASES),
        ran_at="2026-10-01T12:00:00+00:00",
    )
    relevance = pinned(run_relevance(tmp_path / "relevance", NOTHING_RELEVANT))
    chat = pinned(
        run_chat(
            tmp_path / "chat",
            [answered("AB 1"), assessed("SB 1", "declined"), STAGE_FAILURE],
        )
    )
    extraction = pinned(run_extraction(tmp_path / "extraction"))

    card = Scorecard.build(
        [ReportDocument.load(path) for path in (relevance, chat, extraction)],
        baseline="auto",
    )

    assert card.exit_code == 1
    assert markdown(
        card,
        baseline=baseline,
        relevance=relevance,
        chat=chat,
        extraction=extraction,
    ) == (
        "| axis | label quality | primary metric | value | change | scored / "
        "selected | failure rate | comparison status |\n"
        "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
        "| relevance | gold | relevant_f1 | 0.000 (0/3) | -0.667 | 5/5 | 0.000 "
        "(0/5) | comparable |\n"
        "| chat | unlabeled | answer_quality | no quality metric | - | 2/3 "
        "| 0.333 (1/3) | no earlier run |\n"
        "| extraction | silver | node_f1 | unavailable (no case contributed to "
        "the denominator) | - | 1/1 | 0.000 (0/1) | no earlier run |\n"
        "\n"
        "## relevance: relevant_f1 0.000 (-0.667 against the baseline)\n"
        "\n"
        "Population: label quality gold, selection scope full; 5 selected, 5 "
        "scored, 0 failed, 0 unresolved.\n"
        "\n"
        "Baseline: `<baseline>` (comparable).\n"
        "\n"
        "| metric | value | baseline value | change | scored / selected | "
        "aggregation |\n"
        "| --- | --- | --- | --- | --- | --- |\n"
        "| relevant_f1 | 0.000 (0/3) | 0.667 (4/6) | -0.667 | 5/5 | pooled |\n"
        "| relevant_precision | unavailable (0/0) | 0.667 (2/3) | unavailable |"
        " 5/5 | pooled |\n"
        "| relevant_recall | 0.000 (0/3) | 0.667 (2/3) | -0.667 | 5/5 | pooled "
        "|\n"
        "| accuracy | 0.400 (2/5) | 0.600 (3/5) | -0.200 | 5/5 | rate |\n"
        "| true_positives | 0.000 (0/5) | 0.400 (2/5) | -0.400 | 5/5 | rate |\n"
        "| false_positives | 0.000 (0/5) | 0.200 (1/5) | -0.200 | 5/5 | rate |\n"
        "| false_negatives | 0.600 (3/5) | 0.200 (1/5) | +0.400 | 5/5 | rate |\n"
        "| true_negatives | 0.400 (2/5) | 0.200 (1/5) | +0.200 | 5/5 | rate |\n"
        "| execution_failure_rate | 0.000 (0/5) | 0.000 (0/5) | +0.000 | 5/5 | "
        "rate |\n"
        "\n"
        "- relevant_precision (pooled) is unavailable: no case contributed to "
        "the denominator\n"
        "\n"
        "Provenance: commit 1234567 (clean worktree); Model Deployment local "
        "stub; prompts relevance cdcdcdcdcdcd; Data Set abababababab; headline "
        "relevance-v1; [report](<relevance>); no trace.\n"
        "\n"
        "## chat: answer_quality unavailable (Unlabeled Set: no quality metric)\n"
        "\n"
        "Population: label quality unlabeled, selection scope full; 3 selected,"
        " 2 scored, 1 failed, 0 unresolved.\n"
        "\n"
        "Baseline: none (no earlier run).\n"
        "\n"
        "| metric | value | baseline value | change | scored / selected | "
        "aggregation |\n"
        "| --- | --- | --- | --- | --- | --- |\n"
        "| answer_quality | unavailable | - | - | 0/3 | rate |\n"
        "| completed_answer_rate | 0.333 (1/3) | - | - | 3/3 | rate |\n"
        "| declined_rate | 0.333 (1/3) | - | - | 3/3 | rate |\n"
        "| deferred_rate | 0.000 (0/3) | - | - | 3/3 | rate |\n"
        "| needs_edit_rate | 0.000 (0/3) | - | - | 3/3 | rate |\n"
        "| task_duration_p50 | <duration> | - | - | 2/3 | quantile |\n"
        "| task_duration_p95 | <duration> | - | - | 2/3 | quantile |\n"
        "| execution_failure_rate | 0.333 (1/3) | - | - | 3/3 | rate |\n"
        "\n"
        "- answer_quality (rate) is unavailable: Unlabeled Set: no quality "
        "metric\n"
        "\n"
        "Provenance: commit 1234567 (clean worktree); Model Deployment local "
        "stub; prompts chat cdcdcdcdcdcd; Data Set abababababab; headline "
        "chat-v1; [report](<chat>); no trace.\n"
        "\n"
        "## extraction: node_f1 unavailable (no case contributed to the "
        "denominator)\n"
        "\n"
        "Population: label quality silver, selection scope full; 1 selected, 1 "
        "scored, 0 failed, 0 unresolved.\n"
        "\n"
        "Baseline: none (no earlier run).\n"
        "\n"
        "| metric | value | baseline value | change | scored / selected | "
        "aggregation |\n"
        "| --- | --- | --- | --- | --- | --- |\n"
        "| node_f1 | unavailable (0/0) | - | - | 1/1 | pooled |\n"
        "| node_precision | unavailable (0/0) | - | - | 1/1 | pooled |\n"
        "| node_recall | unavailable (0/0) | - | - | 1/1 | pooled |\n"
        "| relationship_precision | unavailable (0/0) | - | - | 1/1 | pooled |\n"
        "| relationship_recall | unavailable (0/0) | - | - | 1/1 | pooled |\n"
        "| relationship_f1 | unavailable (0/0) | - | - | 1/1 | pooled |\n"
        "| node_f1 | 1.000 | - | - | 1/1 | per_case_mean |\n"
        "| relationship_f1 | 1.000 | - | - | 1/1 | per_case_mean |\n"
        "| StayedInsideTheNewsOntology | 1.000 | - | - | 1/1 | per_case_mean |\n"
        "| execution_failure_rate | 0.000 (0/1) | - | - | 1/1 | rate |\n"
        "\n"
        "- node_f1 (pooled) is unavailable: no case contributed to the "
        "denominator\n"
        "- node_precision (pooled) is unavailable: no case contributed to the "
        "denominator\n"
        "- node_recall (pooled) is unavailable: no case contributed to the "
        "denominator\n"
        "- relationship_precision (pooled) is unavailable: no case contributed "
        "to the denominator\n"
        "- relationship_recall (pooled) is unavailable: no case contributed to "
        "the denominator\n"
        "- relationship_f1 (pooled) is unavailable: no case contributed to the "
        "denominator\n"
        "\n"
        "Provenance: commit 1234567 (clean worktree); Model Deployment local "
        "stub; prompts extraction cdcdcdcdcdcd; Data Set abababababab; headline"
        " extraction-v1; [report](<extraction>); no trace.\n"
        "\n"
        "<details>\n"
        "<summary>Diagnostic rows</summary>\n"
        "\n"
        "| metric | value | scored / selected | aggregation |\n"
        "| --- | --- | --- | --- |\n"
        "| sub_label_accuracy | unavailable | 0/1 | per_case_mean |\n"
        "| node_property_accuracy | unavailable | 0/1 | per_case_mean |\n"
        "| claim_property_accuracy | unavailable | 0/1 | per_case_mean |\n"
        "| stance_alignment_accuracy | unavailable | 0/1 | per_case_mean |\n"
        "\n"
        "- sub_label_accuracy (per_case_mean) is unavailable: no case "
        "contributed to the denominator\n"
        "- node_property_accuracy (per_case_mean) is unavailable: no case "
        "contributed to the denominator\n"
        "- claim_property_accuracy (per_case_mean) is unavailable: no case "
        "contributed to the denominator\n"
        "- stance_alignment_accuracy (per_case_mean) is unavailable: no case "
        "contributed to the denominator\n"
        "\n"
        "</details>\n"
    )
