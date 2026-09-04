"""Contracts that keep an Evaluation Run findable in Logfire afterwards."""

from unittest.mock import patch

from knowledge_map.evaluation import run_data_set, trace_url
from knowledge_map.evaluation.data_set import (
    EvaluationCase,
    EvaluationDataSet,
    EvaluationSplit,
)


def _data_set(task: str = "relevance") -> EvaluationDataSet:
    return EvaluationDataSet(
        task=task,
        description="one case",
        cases=[
            EvaluationCase(
                id="case-1",
                description="a case",
                task_input="in",
                expected_output="out",
                split=EvaluationSplit.HELD_OUT,
            )
        ],
    )


def test_the_experiment_is_named_for_the_task_not_the_wrapper():
    """`run_case` names this module's plumbing; the Data Set names the run."""
    report = run_data_set(_data_set(), task=lambda _: "out", evaluators=())

    assert report.name == "relevance"


def test_experiment_metadata_reaches_the_report():
    report = run_data_set(
        _data_set(),
        task=lambda _: "out",
        evaluators=(),
        experiment_metadata={"commit": "abc1234", "split": "held-out"},
    )

    assert report.experiment_metadata == {"commit": "abc1234", "split": "held-out"}


def test_every_case_records_the_trace_it_ran_in():
    report = run_data_set(_data_set(), task=lambda _: "out", evaluators=())

    assert all(case.trace_id for case in report.cases)


def test_trace_url_addresses_the_project_the_run_reported_to():
    report = run_data_set(_data_set(), task=lambda _: "out", evaluators=())

    with patch(
        "knowledge_map.evaluation.report_file.project_url",
        return_value="https://logfire-us.pydantic.dev/acme/project",
    ):
        url = trace_url(report)

    assert url is not None
    assert url.startswith("https://logfire-us.pydantic.dev/acme/project?q=")
    assert report.trace_id in url


def test_no_trace_url_is_better_than_a_dead_one():
    """A run with no known project yields nothing, not a link that 404s."""
    report = run_data_set(_data_set(), task=lambda _: "out", evaluators=())

    with patch(
        "knowledge_map.evaluation.report_file.project_url", return_value=None
    ):
        assert trace_url(report) is None


def test_an_unrecorded_run_yields_no_trace_url():
    """OpenTelemetry's all-zero id means nothing traced this; say so."""
    report = run_data_set(_data_set(), task=lambda _: "out", evaluators=())
    report.trace_id = "0" * 32

    with patch(
        "knowledge_map.evaluation.report_file.project_url",
        return_value="https://logfire-us.pydantic.dev/acme/project",
    ):
        assert trace_url(report) is None
