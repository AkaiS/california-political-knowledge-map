"""Evaluation Runs over authored outputs, saved as Evaluation Reports.

The engine-run seam: a stub task returns each case's authored output, and the
run goes through the evaluation engine and the report checkpoint with the
task's own case evaluators and headline definition. No model is called and
no telemetry is sent.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any
from unittest.mock import patch

from pydantic import BaseModel
from pydantic_evals.lifecycle import CaseLifecycle

from knowledge_map.evaluation import (
    EvaluationCase,
    EvaluationDataSet,
    LabelQuality,
    run_data_set,
)
from knowledge_map.evaluation.persistence import ReportCheckpoint
from knowledge_map.evaluation.tasks import task_named
from knowledge_map.schemas import DeploymentKind, ModelDeployment

HEADLINE_COLUMNS = [
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


def run_task(
    directory: Path,
    task_name: str,
    cases: Sequence[tuple[str, Any, Any]],
    *,
    task_input: Callable[[str], BaseModel],
    label_quality: LabelQuality,
) -> Path:
    """Run ``cases`` -- (id, expectation, authored output) -- and save the report.

    ``task_input`` builds each case's input from its id. An authored output
    that is an exception is raised by the stub task. A ``KeyboardInterrupt``
    stops the run the way an operator does, and the saved report is marked
    incomplete as ``ca-map eval run`` marks it.
    """

    task = task_named(task_name)
    data_set = EvaluationDataSet(
        task=task_name,
        description="headline fixtures",
        cases=tuple(
            EvaluationCase(
                id=case_id,
                description=case_id,
                task_input=task_input(case_id),
                expected_output=expected,
            )
            for case_id, expected, _ in cases
        ),
    )
    outputs = [
        (case.task_input, output)
        for case, (_, _, output) in zip(data_set.cases, cases, strict=True)
    ]

    def stub(case_input):
        output = next(output for given, output in outputs if given == case_input)
        if isinstance(output, BaseException):
            raise output
        return output

    directory.mkdir(parents=True, exist_ok=True)
    source = directory / f"{task_name}.yaml"
    source.write_text("authored fixtures")
    checkpoint = ReportCheckpoint(
        task=task_name,
        cases=data_set.cases,
        deployment=ModelDeployment(kind=DeploymentKind.LOCAL, model="stub"),
        data_set_path=source,
        label_quality=label_quality,
        experiment_metadata={"headline_version": task.headline.version},
        root=directory / "reports",
    )
    try:
        with patch("knowledge_map.evaluation.engine.setup_telemetry", lambda: None):
            report = run_data_set(
                data_set,
                task=stub,
                evaluators=task.evaluators,
                report_evaluators=(task.headline.evaluator(),),
                case_lifecycle=CaseLifecycle,
                checkpoint=checkpoint,
            )
    except BaseException as error:  # noqa: BLE001 -- mirrors the CLI's interruption marker
        checkpoint.interrupted(f"{type(error).__name__}: {error}")
        return checkpoint.path
    checkpoint.finish(report)
    return checkpoint.path


def headline_table(document: dict) -> list[list]:
    """The saved report's one Headline Metrics table, as its raw rows."""

    tables = [
        analysis
        for analysis in document["report"]["analyses"]
        if analysis.get("title") == "Headline metrics"
    ]
    assert len(tables) == 1
    assert tables[0]["type"] == "table"
    assert tables[0]["columns"] == HEADLINE_COLUMNS
    return tables[0]["rows"]


def headline_rows(document: dict) -> dict[tuple[str, str], dict]:
    """Each headline row by its metric and aggregation, read by column name."""

    return {
        (row[0], row[5]): dict(zip(HEADLINE_COLUMNS, row, strict=True))
        for row in headline_table(document)
    }
