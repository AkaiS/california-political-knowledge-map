"""A completed Extraction Evaluation Run records its Headline Metrics.

Each test runs authored outputs through the evaluation engine and the report
checkpoint with Extraction's own case evaluators and headline definition, then
reads the saved Evaluation Report. No model is called.
"""

from __future__ import annotations

import json

import pytest
from engine_runs import headline_rows, headline_table, run_task

from knowledge_map.evaluation import LabelQuality
from knowledge_map.evaluation.tasks.extraction import (
    ExtractionExpectation,
    ExtractionInput,
    ExtractionOutput,
)
from knowledge_map.schemas import Node, Relationship

NO_DENOMINATOR = "no case contributed to the denominator"


def node(name, label="Organization", subs=(), **properties):
    return Node(name=name, label=label, sub_labels=list(subs), properties=properties)


def claim(source, relationship_type, target, **properties):
    return Relationship(
        source=source,
        target=target,
        relationship_type=relationship_type,
        properties=properties,
    )


def saved_run(directory, cases):
    path = run_task(
        directory,
        "extraction",
        cases,
        task_input=lambda case_id: ExtractionInput(
            url=case_id, title=case_id, chunk_index=0, text=case_id
        ),
        label_quality=LabelQuality.SILVER,
    )
    return json.loads(path.read_text())


# One large chunk the model mostly got right, one small chunk it got wrong,
# and one chunk both sides left empty.  Pooled F1 weighs the large chunk's
# many nodes; the per-case mean weighs each chunk once.
LARGE = (
    "large",
    ExtractionExpectation(
        nodes=[
            node("Uber", subs=["Corporation"], sector="rideshare"),
            node("Lyft", subs=["Corporation"]),
            node("SB 371", "Bill"),
            node("AB 5", "Bill"),
            node("Gavin Newsom", "Person"),
            node("Teamsters", subs=["Union"]),
            node("Senate", "Organization"),
            node("Assembly", "Organization"),
        ],
        relationships=[
            claim("Uber", "DECLARED_STANCE", "SB 371", alignment="SUPPORTS"),
            claim("Lyft", "LOBBIED_FOR", "AB 5", amount="100"),
        ],
    ),
    ExtractionOutput(
        nodes=[
            node("uber", subs=["Corporation"], sector="rideshare"),
            node("Lyft", subs=["Union"]),
            node("SB 371", "Bill"),
            node("AB 5", "Bill"),
            node("Gavin  Newsom", "Person"),
            node("Teamsters", subs=["Union"]),
        ],
        relationships=[
            claim("Uber", "DECLARED_STANCE", "SB 371", alignment="OPPOSES"),
        ],
    ),
)
SMALL = (
    "small",
    ExtractionExpectation(
        nodes=[node("CARB", subs=["Agency"]), node("Air Resources Board")],
        relationships=[],
    ),
    ExtractionOutput(
        nodes=[node("CARB", subs=["Agency"]), node("ARB")],
        relationships=[claim("CARB", "REGULATES", "ARB")],
        dropped_item_count=2,
    ),
)
BOTH_EMPTY = ("both-empty", ExtractionExpectation(), ExtractionOutput())


def test_completed_run_records_pooled_node_f1_first_with_its_headline_rows(tmp_path):
    document = saved_run(tmp_path, [LARGE, SMALL, BOTH_EMPTY])

    # Nodes: large matched 6 of 6 found and 8 expected (F1 6/7); small matched
    # 1 of 2 and 2 (F1 1/2); both-empty adds nothing and passes at 1.0.
    # Pooled: 7 matched, 8 found, 10 expected.  Per-case: (6/7 + 1/2 + 1) / 3.
    # Relationships: large matched 1 of 1 found and 2 expected (F1 2/3); small
    # matched 0 of 1 found and 0 expected (F1 0); both-empty passes at 1.0.
    # Pooled: 1 matched, 2 found, 2 expected.  Per-case: (2/3 + 0 + 1) / 3.
    assert headline_table(document) == [
        ["node_f1", "primary", 14 / 18, 14.0, 18.0, "pooled", 3, 3, None],
        ["node_precision", "headline", 7 / 8, 7.0, 8.0, "pooled", 3, 3, None],
        ["node_recall", "headline", 7 / 10, 7.0, 10.0, "pooled", 3, 3, None],
        ["relationship_precision", "headline", 1 / 2, 1.0, 2.0, "pooled", 3, 3, None],
        ["relationship_recall", "headline", 1 / 2, 1.0, 2.0, "pooled", 3, 3, None],
        ["relationship_f1", "headline", 2 / 4, 2.0, 4.0, "pooled", 3, 3, None],
        [
            "node_f1",
            "headline",
            pytest.approx((6 / 7 + 1 / 2 + 1) / 3),
            pytest.approx(6 / 7 + 1 / 2 + 1),
            3.0,
            "per_case_mean",
            3,
            3,
            None,
        ],
        [
            "relationship_f1",
            "headline",
            pytest.approx((2 / 3 + 0 + 1) / 3),
            pytest.approx(2 / 3 + 0 + 1),
            3.0,
            "per_case_mean",
            3,
            3,
            None,
        ],
        [
            "StayedInsideTheNewsOntology",
            "headline",
            2 / 3,
            2.0,
            3.0,
            "per_case_mean",
            3,
            3,
            None,
        ],
        ["execution_failure_rate", "headline", 0.0, 0.0, 3.0, "rate", 3, 3, None],
        # Sub-labels: large agrees on 5 of 6 shared nodes, small on 1 of 1.
        [
            "sub_label_accuracy",
            "diagnostic",
            pytest.approx((5 / 6 + 1) / 2),
            pytest.approx(5 / 6 + 1),
            2.0,
            "per_case_mean",
            2,
            3,
            None,
        ],
        # Only large shares a node silver gave properties, and it agrees.
        [
            "node_property_accuracy",
            "diagnostic",
            1.0,
            1.0,
            1.0,
            "per_case_mean",
            1,
            3,
            None,
        ],
        # Only large shares a claim, the stance, and its alignment disagrees.
        [
            "claim_property_accuracy",
            "diagnostic",
            0.0,
            0.0,
            1.0,
            "per_case_mean",
            1,
            3,
            None,
        ],
        [
            "stance_alignment_accuracy",
            "diagnostic",
            0.0,
            0.0,
            1.0,
            "per_case_mean",
            1,
            3,
            None,
        ],
    ]
    assert document["experiment_metadata"]["headline_version"] == "extraction-v1"


def test_a_chunk_both_sides_left_empty_adds_nothing_pooled_but_passes_per_case(
    tmp_path,
):
    rows = headline_rows(saved_run(tmp_path, [BOTH_EMPTY]))

    for metric in ("node_f1", "node_precision", "relationship_recall"):
        pooled = rows[(metric, "pooled")]
        assert (pooled["value"], pooled["numerator"], pooled["denominator"]) == (
            None,
            0.0,
            0.0,
        )
        assert pooled["unavailable_reason"] == NO_DENOMINATOR
    for metric in ("node_f1", "relationship_f1"):
        per_case = rows[(metric, "per_case_mean")]
        assert (per_case["value"], per_case["numerator"], per_case["denominator"]) == (
            1.0,
            1.0,
            1.0,
        )
    # Nothing was shared, so no detail was scored.
    assert rows[("sub_label_accuracy", "per_case_mean")] == {
        "metric": "sub_label_accuracy",
        "role": "diagnostic",
        "value": None,
        "numerator": 0.0,
        "denominator": 0.0,
        "aggregation": "per_case_mean",
        "scored_cases": 0,
        "selected_cases": 1,
        "unavailable_reason": NO_DENOMINATOR,
    }


def test_failed_cases_complete_the_run_and_count_only_toward_execution_failures(
    tmp_path,
):
    clean = headline_rows(saved_run(tmp_path / "clean", [LARGE, SMALL, BOTH_EMPTY]))
    document = saved_run(
        tmp_path / "with-failures",
        [
            LARGE,
            SMALL,
            BOTH_EMPTY,
            ("raised", LARGE[1], RuntimeError("transport exhausted")),
            ("recorded", LARGE[1], ExtractionOutput(failure_type="output_validation")),
        ],
    )

    assert document["evaluation_run"]["status"] == "completed"
    rows = headline_rows(document)
    assert rows.pop(("execution_failure_rate", "rate")) == {
        "metric": "execution_failure_rate",
        "role": "headline",
        "value": 2 / 5,
        "numerator": 2.0,
        "denominator": 5.0,
        "aggregation": "rate",
        "scored_cases": 5,
        "selected_cases": 5,
        "unavailable_reason": None,
    }
    del clean[("execution_failure_rate", "rate")]
    # Every quality row reads exactly as it did without the failures, over
    # the larger run population.
    assert {key: {**row, "selected_cases": 5} for key, row in clean.items()} == rows


def test_unreadable_output_records_evaluator_errors_the_same_way_on_every_run(
    tmp_path,
):
    cases = [LARGE, SMALL, BOTH_EMPTY, ("unreadable", LARGE[1], None)]
    first = saved_run(tmp_path / "first", cases)
    second = saved_run(tmp_path / "second", cases)

    for document in (first, second):
        assert document["evaluation_run"]["status"] == "completed"
        assert document["report"]["analyses"] == []
    (failure,) = first["report"]["report_evaluator_failures"]
    assert failure["source"] == {
        "name": "HeadlineMetrics",
        "arguments": ["extraction-v1"],
    }
    assert (
        first["report"]["report_evaluator_failures"]
        == second["report"]["report_evaluator_failures"]
    )
