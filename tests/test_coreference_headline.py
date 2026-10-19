"""Completed Coreference and Coreference annotator runs record Headline Metrics.

Each test runs authored outputs through the evaluation engine and the report
checkpoint with the task's own case evaluators and headline definition, then
reads the saved Evaluation Report. Both tasks run the same fixtures, so their
agreement rows can be read side by side. No model is called.
"""

from __future__ import annotations

import json

import pytest
from engine_runs import headline_table, run_task

from knowledge_map.evaluation import LabelQuality
from knowledge_map.evaluation.tasks.coreference import (
    CoreferenceExpectation,
    CoreferenceInput,
    CoreferenceOutput,
)
from knowledge_map.schemas import MentionSpan, MentionSpanOutcome

TASKS = ("coreference", "coreference_annotator")


def span(label, text, entity):
    return MentionSpan(
        sentence_label=label, mention_text=text, canonical_entity_name=entity
    )


def critic(outcome, mention_span):
    return MentionSpanOutcome(
        mention_span=mention_span,
        stage="critic",
        outcome=outcome,
        reason=None if outcome == "accepted" else "not supported",
    )


def silver(*spans):
    return CoreferenceExpectation(mention_spans=list(spans))


def resolved(spans, outcomes=()):
    return CoreferenceOutput(mention_spans=list(spans), outcomes=list(outcomes))


def saved_run(directory, task_name, cases):
    path = run_task(
        directory,
        task_name,
        cases,
        task_input=lambda case_id: CoreferenceInput(
            url=case_id, title=case_id, content=case_id
        ),
        label_quality=LabelQuality.SILVER,
    )
    return json.loads(path.read_text())


# Merged: the model found three of silver's four mentions and one spurious
# one, and put Atkins in Newsom's cluster.  Over the three shared mentions B³
# precision is (2/3 + 1/3 + 2/3) / 3 and recall is (1 + 1 + 1) / 3.
HE = span("1", "he", "Gavin Newsom")
SHE = span("2", "she", "Toni Atkins")
GOVERNOR = span("3", "the governor", "Gavin Newsom")
IT = span("4", "it", "SB 1")
THEY = span("5", "they", "Senate")
MERGED_SILVER = silver(HE, SHE, GOVERNOR, IT)
MERGED = (
    "merged",
    MERGED_SILVER,
    resolved(
        [HE, span("2", "she", "Gavin Newsom"), GOVERNOR, THEY],
        [
            critic("accepted", HE),
            critic("accepted", span("2", "she", "Gavin Newsom")),
            critic("accepted", GOVERNOR),
            critic("accepted", THEY),
            critic("rejected", span("4", "it", "SB 2")),
            MentionSpanOutcome(
                mention_span=span("6", "its", "Senate"),
                stage="validation",
                outcome="discarded",
                reason="mention not found",
            ),
        ],
    ),
)
# Split: the model found both mentions of SB 1 but named the second
# "Senate Bill 1", splitting one cluster in two.  B³ precision is (1 + 1) / 2
# and recall (1/2 + 1/2) / 2.
BILL = span("2", "the bill", "SB 1")
SPLIT = (
    "split",
    silver(span("1", "it", "SB 1"), BILL, span("3", "he", "Gavin Newsom")),
    resolved(
        [span("1", "it", "SB 1"), span("2", "the bill", "Senate Bill 1")],
        [
            critic("accepted", span("1", "it", "SB 1")),
            critic("accepted", span("2", "the bill", "Senate Bill 1")),
            critic("rejected", span("3", "he", "Gavin Newsom")),
        ],
    ),
)
# Nothing shared: the model's one mention is one silver never annotated.
NOTHING_SHARED = (
    "nothing-shared",
    silver(SHE),
    resolved([THEY], [critic("accepted", THEY)]),
)

# Mentions: merged matched 3 of 4 found and 4 expected (F1 3/4); split 2 of 2
# and 3 (F1 4/5); nothing-shared 0 of 1 and 1 (F1 0).  Pooled: 5 matched, 7
# found, 8 expected.  B³ pools 11/3 precision credit and 4 recall credit over
# 5 shared mentions.  Canonical entity: 2 of 3 shared in merged, 1 of 2 in
# split; nothing-shared shares nothing and contributes nothing.
AGREEMENT_ROWS = [
    ["span_f1", "primary", 10 / 15, 10.0, 15.0, "pooled", 3, 3, None],
    ["span_precision", "headline", 5 / 7, 5.0, 7.0, "pooled", 3, 3, None],
    ["span_recall", "headline", 5 / 8, 5.0, 8.0, "pooled", 3, 3, None],
    [
        "cluster_precision",
        "headline",
        pytest.approx(11 / 15),
        pytest.approx(11 / 3),
        5.0,
        "pooled",
        3,
        3,
        None,
    ],
    ["cluster_recall", "headline", 4 / 5, 4.0, 5.0, "pooled", 3, 3, None],
    [
        "cluster_f1",
        "headline",
        pytest.approx(88 / 115),
        pytest.approx(88 / 3),
        pytest.approx(115 / 3),
        "pooled",
        3,
        3,
        None,
    ],
    ["entity_accuracy", "headline", 3 / 5, 3.0, 5.0, "pooled", 2, 3, None],
    [
        "span_f1",
        "headline",
        pytest.approx((3 / 4 + 4 / 5 + 0) / 3),
        pytest.approx(3 / 4 + 4 / 5),
        3.0,
        "per_case_mean",
        3,
        3,
        None,
    ],
    ["execution_failure_rate", "headline", 0.0, 0.0, 3.0, "rate", 3, 3, None],
]


@pytest.mark.parametrize(
    ("task_name", "version"),
    [
        ("coreference", "coreference-v1"),
        ("coreference_annotator", "coreference_annotator-v1"),
    ],
)
def test_both_tasks_record_pooled_span_f1_first_and_the_same_agreement_rows(
    tmp_path, task_name, version
):
    document = saved_run(tmp_path, task_name, [MERGED, SPLIT, NOTHING_SHARED])

    # Neither table has a Critic row or any diagnostic row.
    assert headline_table(document) == AGREEMENT_ROWS
    assert document["experiment_metadata"]["headline_version"] == version


NO_DENOMINATOR = "no case contributed to the denominator"
# The model resolved nothing, so it shares no mention with silver either.
MISSED_EVERYTHING = ("missed-everything", silver(HE, GOVERNOR), resolved([]))


@pytest.mark.parametrize("task_name", TASKS)
def test_cases_sharing_no_mention_leave_clusters_and_entities_without_a_value(
    tmp_path, task_name
):
    rows = headline_table(
        saved_run(tmp_path, task_name, [NOTHING_SHARED, MISSED_EVERYTHING])
    )

    # Mentions: 0 matched of 1 found and 3 expected.
    assert rows[:3] == [
        ["span_f1", "primary", 0.0, 0.0, 4.0, "pooled", 2, 2, None],
        ["span_precision", "headline", 0.0, 0.0, 1.0, "pooled", 2, 2, None],
        ["span_recall", "headline", 0.0, 0.0, 3.0, "pooled", 2, 2, None],
    ]
    assert rows[3:7] == [
        [metric, "headline", None, 0.0, 0.0, "pooled", 2, 2, NO_DENOMINATOR]
        for metric in ("cluster_precision", "cluster_recall", "cluster_f1")
    ] + [
        ["entity_accuracy", "headline", None, 0.0, 0.0, "pooled", 0, 2, NO_DENOMINATOR]
    ]
    assert rows[7] == [
        "span_f1",
        "headline",
        0.0,
        0.0,
        2.0,
        "per_case_mean",
        2,
        2,
        None,
    ]


@pytest.mark.parametrize("task_name", TASKS)
def test_failed_cases_complete_the_run_and_count_only_toward_execution_failures(
    tmp_path, task_name
):
    clean = headline_table(
        saved_run(tmp_path / "clean", task_name, [MERGED, SPLIT, NOTHING_SHARED])
    )
    document = saved_run(
        tmp_path / "with-failures",
        task_name,
        [
            MERGED,
            SPLIT,
            NOTHING_SHARED,
            ("raised", MERGED_SILVER, RuntimeError("transport exhausted")),
            # A run the Critic emptied keeps its rejections in its output.
            (
                "recorded",
                MERGED_SILVER,
                CoreferenceOutput(
                    outcomes=[critic("rejected", HE), critic("rejected", SHE)],
                    failure_type="zero_survivors",
                ),
            ),
        ],
    )

    assert document["evaluation_run"]["status"] == "completed"
    rows = headline_table(document)
    assert rows.pop(8) == [
        "execution_failure_rate",
        "headline",
        2 / 5,
        2.0,
        5.0,
        "rate",
        5,
        5,
        None,
    ]
    del clean[8]
    # Every quality row reads exactly as it did without the failures, over
    # the larger run population.
    assert [[*row[:7], 5, row[8]] for row in clean] == rows


# A Story silver found nothing to resolve in.  Both tasks record an empty
# answer as the "no_mentions_returned" failure.
NOTHING_TO_RESOLVE = (
    "nothing-to-resolve",
    silver(),
    CoreferenceOutput(failure_type="no_mentions_returned"),
)


@pytest.mark.parametrize("task_name", TASKS)
def test_a_story_both_sides_left_empty_counts_only_as_an_execution_failure(
    tmp_path, task_name
):
    clean = headline_table(
        saved_run(tmp_path / "clean", task_name, [MERGED, SPLIT, NOTHING_SHARED])
    )
    rows = headline_table(
        saved_run(
            tmp_path / "with-empty",
            task_name,
            [MERGED, SPLIT, NOTHING_SHARED, NOTHING_TO_RESOLVE],
        )
    )

    assert rows.pop(8) == [
        "execution_failure_rate",
        "headline",
        1 / 4,
        1.0,
        4.0,
        "rate",
        4,
        4,
        None,
    ]
    del clean[8]
    # It adds nothing to any pooled count and stays out of the per-case mean.
    assert [[*row[:7], 4, row[8]] for row in clean] == rows


@pytest.mark.parametrize(
    ("task_name", "version"),
    [
        ("coreference", "coreference-v1"),
        ("coreference_annotator", "coreference_annotator-v1"),
    ],
)
def test_unreadable_output_records_evaluator_errors_the_same_way_on_every_run(
    tmp_path, task_name, version
):
    cases = [MERGED, SPLIT, ("unreadable", MERGED_SILVER, None)]
    first = saved_run(tmp_path / "first", task_name, cases)
    second = saved_run(tmp_path / "second", task_name, cases)

    for document in (first, second):
        assert document["evaluation_run"]["status"] == "completed"
        assert document["report"]["analyses"] == []
    (failure,) = first["report"]["report_evaluator_failures"]
    assert failure["source"] == {"name": "HeadlineMetrics", "arguments": [version]}
    assert (
        first["report"]["report_evaluator_failures"]
        == second["report"]["report_evaluator_failures"]
    )
