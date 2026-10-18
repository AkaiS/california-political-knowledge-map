"""A completed Extraction Evaluation Run records its Headline Metrics.

Each test runs authored outputs through the evaluation engine and the report
checkpoint with Extraction's own case evaluators and headline definition, then
reads the saved Evaluation Report. No model is called.
"""

from __future__ import annotations

import json

import pytest
from pydantic_evals.lifecycle import CaseLifecycle

from knowledge_map.evaluation import (
    EvaluationCase,
    EvaluationDataSet,
    LabelQuality,
    run_data_set,
)
from knowledge_map.evaluation.persistence import ReportCheckpoint
from knowledge_map.evaluation.tasks import task_named
from knowledge_map.evaluation.tasks.extraction import (
    ExtractionExpectation,
    ExtractionInput,
    ExtractionOutput,
)
from knowledge_map.schemas import DeploymentKind, ModelDeployment, Node, Relationship

COLUMNS = [
    "metric",
    "role",
    "value",
    "numerator",
    "denominator",
    "aggregation",
    "scored_cases",
    "selected_cases",
    "unavailable_reason",
]
NO_DENOMINATOR = "no case contributed to the denominator"


@pytest.fixture(autouse=True)
def disable_telemetry(monkeypatch):
    monkeypatch.setattr("knowledge_map.evaluation.engine.setup_telemetry", lambda: None)


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
    """Run ``cases`` -- (id, expectation, authored output) -- and read the report.

    An authored output that is an exception is raised by the stub task.
    """

    task = task_named("extraction")
    data_set = EvaluationDataSet(
        task="extraction",
        description="headline fixtures",
        cases=tuple(
            EvaluationCase(
                id=case_id,
                description=case_id,
                task_input=ExtractionInput(
                    url=case_id, title=case_id, chunk_index=0, text=case_id
                ),
                expected_output=expected,
            )
            for case_id, expected, _ in cases
        ),
    )
    outputs = {case_id: output for case_id, _, output in cases}

    def stub(case_input: ExtractionInput):
        output = outputs[case_input.url]
        if isinstance(output, BaseException):
            raise output
        return output

    directory.mkdir(parents=True, exist_ok=True)
    source = directory / "extraction.yaml"
    source.write_text("authored fixtures")
    checkpoint = ReportCheckpoint(
        task="extraction",
        cases=data_set.cases,
        deployment=ModelDeployment(kind=DeploymentKind.LOCAL, model="stub"),
        data_set_path=source,
        label_quality=LabelQuality.SILVER,
        experiment_metadata={"headline_version": task.headline.version},
        root=directory / "reports",
    )
    report = run_data_set(
        data_set,
        task=stub,
        evaluators=task.evaluators,
        report_evaluators=(task.headline.evaluator(),),
        case_lifecycle=CaseLifecycle,
        checkpoint=checkpoint,
    )
    checkpoint.finish(report)
    return json.loads(checkpoint.path.read_text())


def headline_table(document):
    tables = [
        analysis
        for analysis in document["report"]["analyses"]
        if analysis.get("title") == "Headline metrics"
    ]
    assert len(tables) == 1
    assert tables[0]["type"] == "table"
    assert tables[0]["columns"] == COLUMNS
    return tables[0]["rows"]


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
    rows = {
        (row[0], row[5]): row
        for row in headline_table(saved_run(tmp_path, [BOTH_EMPTY]))
    }

    for metric in ("node_f1", "node_precision", "relationship_recall"):
        assert rows[(metric, "pooled")][2:5] == [None, 0.0, 0.0]
        assert rows[(metric, "pooled")][8] == NO_DENOMINATOR
    assert rows[("node_f1", "per_case_mean")][2:5] == [1.0, 1.0, 1.0]
    assert rows[("relationship_f1", "per_case_mean")][2:5] == [1.0, 1.0, 1.0]
    # Nothing was shared, so no detail was scored.
    assert rows[("sub_label_accuracy", "per_case_mean")] == [
        "sub_label_accuracy",
        "diagnostic",
        None,
        0.0,
        0.0,
        "per_case_mean",
        0,
        1,
        NO_DENOMINATOR,
    ]


def test_failed_cases_complete_the_run_and_count_only_toward_execution_failures(
    tmp_path,
):
    clean = headline_table(saved_run(tmp_path / "clean", [LARGE, SMALL, BOTH_EMPTY]))
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
    rows = headline_table(document)
    assert rows[-5] == [
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
    # Every quality row reads exactly as it did without the failures, over
    # the larger run population.
    quality = [row for row in rows if row[0] != "execution_failure_rate"]
    assert [row[:7] for row in quality] == [
        row[:7] for row in clean if row[0] != "execution_failure_rate"
    ]
    assert {row[7] for row in quality} == {5}
