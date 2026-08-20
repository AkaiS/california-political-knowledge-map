"""Run an Evaluation Gold Set through ``pydantic-evals``.

The Gold Set is a file and the report is a file; this module is what runs
between them. It holds no persistence and resolves no plan — see ADR 0017.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable, Sequence
from typing import Any

from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import Evaluator, ReportEvaluator
from pydantic_evals.reporting import EvaluationReport

from .gold_set import EvaluationCase, EvaluationGoldSet, EvaluationSplit


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
    return dataset.evaluate_sync(
        _synchronous(task), progress=False, max_concurrency=max_concurrency
    )


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
