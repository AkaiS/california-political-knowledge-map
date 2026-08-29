"""Run an Evaluation Gold Set through ``pydantic-evals``.

The Gold Set is a file and the report is a file; this module is what runs
between them. It holds no persistence and resolves no plan — see ADR 0017.
"""

from __future__ import annotations

import asyncio
import inspect
import threading
from collections.abc import Callable, Sequence
from contextvars import ContextVar, Token
from typing import Any

from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import Evaluator, ReportEvaluator
from pydantic_evals.lifecycle import CaseLifecycle
from pydantic_evals.reporting import EvaluationReport

from knowledge_map.utils.models import request_provenance_scope

from .gold_set import EvaluationCase, EvaluationGoldSet, EvaluationSplit

_CURRENT_EVALUATION_CASE_ID: ContextVar[str | None] = ContextVar(
    "current_evaluation_case_id", default=None
)


class _RequestProvenanceLifecycle(CaseLifecycle[Any, Any, Any]):
    """Expose each framework case id to its task execution context."""

    def __init__(self, case: Any) -> None:
        super().__init__(case)
        self._case_id_token: Token[str | None] | None = None

    async def setup(self) -> None:
        self._case_id_token = _CURRENT_EVALUATION_CASE_ID.set(self.case.name)

    async def teardown(self, result: Any) -> None:
        del result
        if self._case_id_token is not None:
            _CURRENT_EVALUATION_CASE_ID.reset(self._case_id_token)
            self._case_id_token = None


def build_dataset(
    gold_set: EvaluationGoldSet[Any, Any, Any],
    *,
    evaluators: Sequence[Evaluator],
    report_evaluators: Sequence[ReportEvaluator] = (),
    split: EvaluationSplit | None = None,
) -> Dataset[Any, Any, Any]:
    """Project a Gold Set into one multi-case Pydantic Evals Dataset."""
    cases = gold_set.split(split) if split is not None else gold_set.cases
    if not cases:
        raise ValueError(
            f"{gold_set.task} has no cases"
            + (f" in the {split.value} split" if split is not None else "")
        )
    return Dataset(
        name=gold_set.task,
        cases=[_framework_case(case) for case in cases],
        evaluators=tuple(evaluators),
        report_evaluators=tuple(report_evaluators),
    )


def run_gold_set(
    gold_set: EvaluationGoldSet[Any, Any, Any],
    *,
    task: Callable[[Any], Any],
    evaluators: Sequence[Evaluator],
    report_evaluators: Sequence[ReportEvaluator] = (),
    split: EvaluationSplit | None = None,
    max_concurrency: int = 1,
) -> EvaluationReport[Any, Any, Any]:
    """Execute every case in ``gold_set`` against ``task``."""
    if max_concurrency < 1:
        raise ValueError("max_concurrency must be greater than 0")
    dataset = build_dataset(
        gold_set,
        evaluators=evaluators,
        report_evaluators=report_evaluators,
        split=split,
    )
    records_by_case: dict[str, list[dict[str, object]]] = {}
    records_lock = threading.Lock()
    synchronous_task = _synchronous(task)

    def run_case(task_input: Any) -> Any:
        case_id = _CURRENT_EVALUATION_CASE_ID.get()
        if case_id is None:
            return synchronous_task(task_input)

        with request_provenance_scope(case_id) as records:
            try:
                return synchronous_task(task_input)
            finally:
                with records_lock:
                    records_by_case[case_id] = [record.as_dict() for record in records]

    report = dataset.evaluate_sync(
        run_case,
        progress=False,
        max_concurrency=max_concurrency,
        lifecycle=_RequestProvenanceLifecycle,
    )
    for report_case in report.cases:
        with records_lock:
            report_case.attributes["request_provenance"] = records_by_case.get(
                report_case.name, []
            )
    for report_failure in report.failures:
        with records_lock:
            # pydantic-evals' failure dataclass has no attributes mapping, so
            # retain the same per-case evidence as a report-only extension.
            report_failure.request_provenance = records_by_case.get(
                report_failure.name, []
            )
    return report


def _framework_case(case: EvaluationCase[Any, Any, Any]) -> Case[Any, Any, Any]:
    """Name the framework case by the authored id so reports stay comparable."""
    return Case(
        name=case.id,
        inputs=case.task_input,
        expected_output=case.expected_output,
        metadata=case.metadata,
    )


def _synchronous(task: Callable[[Any], Any]) -> Callable[[Any], Any]:
    if not inspect.iscoroutinefunction(task):
        return task

    def run(task_input: Any) -> Any:
        return asyncio.run(task(task_input))

    return run
