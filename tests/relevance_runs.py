"""Relevance Evaluation Runs over authored outputs, saved as Evaluation Reports.

The engine-run seam: a stub task returns each case's authored output, and the
run goes through the evaluation engine and the report checkpoint with
Relevance's own case evaluators and headline definition. No model is called.
Callers disable telemetry, as every engine-run test does.
"""

from __future__ import annotations

from pathlib import Path

from pydantic_evals.lifecycle import CaseLifecycle

from knowledge_map.evaluation import (
    EvaluationCase,
    EvaluationDataSet,
    LabelQuality,
    run_data_set,
)
from knowledge_map.evaluation.persistence import ReportCheckpoint
from knowledge_map.evaluation.tasks import task_named
from knowledge_map.evaluation.tasks.relevance import (
    RelevanceExpectation,
    RelevanceInput,
)
from knowledge_map.schemas import DeploymentKind, ModelDeployment

RELEVANT = RelevanceExpectation(classification="RELEVANT")
IRRELEVANT = RelevanceExpectation(classification="IRRELEVANT")

CONFUSION_CASES = [
    ("tp-1", RELEVANT, RELEVANT),
    ("tp-2", RELEVANT, RELEVANT),
    ("fp", IRRELEVANT, RELEVANT),
    ("fn", RELEVANT, IRRELEVANT),
    ("both-negative", IRRELEVANT, IRRELEVANT),
]


def run_relevance(directory: Path, cases) -> Path:
    """Run ``cases`` -- (id, expected label, authored output) -- and save the report.

    An authored output that is an exception is raised by the stub task. A
    ``KeyboardInterrupt`` stops the run the way an operator does, and the
    saved report is marked incomplete as ``ca-map eval run`` marks it.
    """

    task = task_named("relevance")
    data_set = EvaluationDataSet(
        task="relevance",
        description="headline fixtures",
        cases=tuple(
            EvaluationCase(
                id=case_id,
                description=case_id,
                task_input=RelevanceInput(url=case_id, headline=case_id),
                expected_output=expected,
            )
            for case_id, expected, _ in cases
        ),
    )
    outputs = {case_id: output for case_id, _, output in cases}

    def stub(case_input: RelevanceInput):
        output = outputs[case_input.url]
        if isinstance(output, BaseException):
            raise output
        return output

    directory.mkdir(parents=True, exist_ok=True)
    source = directory / "relevance.yaml"
    source.write_text("authored fixtures")
    checkpoint = ReportCheckpoint(
        task="relevance",
        cases=data_set.cases,
        deployment=ModelDeployment(kind=DeploymentKind.LOCAL, model="stub"),
        data_set_path=source,
        label_quality=LabelQuality.GOLD,
        experiment_metadata={"headline_version": task.headline.version},
        root=directory / "reports",
    )
    try:
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
