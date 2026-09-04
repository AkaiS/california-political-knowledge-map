"""Run an Evaluation Data Set through ``pydantic-evals``.

The Data Set is a file and the report is a file; this module is what runs
between them. It holds no persistence and resolves no plan — see ADR 0017.
"""

from __future__ import annotations

import asyncio
import inspect
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import Evaluator, EvaluatorContext, ReportEvaluator
from pydantic_evals.lifecycle import CaseLifecycle
from pydantic_evals.reporting import EvaluationReport

from knowledge_map.utils.telemetry import setup_telemetry

from .data_set import EvaluationCase, EvaluationDataSet, EvaluationSplit


class _EvaluationCaseLifecycle(CaseLifecycle[Any, Any, Any]):
    """Attach case-scoped evidence at the framework lifecycle boundary."""

    async def prepare_context(self, ctx: EvaluatorContext) -> EvaluatorContext:
        routes: Counter[tuple[str, str | None]] = Counter()
        for span in ctx.span_tree:
            if span.attributes.get("gen_ai.operation.name") != "chat":
                continue
            response_model = span.attributes.get("gen_ai.response.model")
            if not isinstance(response_model, str):
                continue
            downstream_provider = span.attributes.get(
                "gen_ai.response.downstream_provider"
            )
            if not isinstance(downstream_provider, str):
                downstream_provider = None
            routes[(response_model, downstream_provider)] += 1
        ctx.attributes["model_routes"] = [
            {
                "response_model": response_model,
                "downstream_provider": downstream_provider,
                "request_count": count,
            }
            for (response_model, downstream_provider), count in sorted(
                routes.items(), key=lambda item: (item[0][0], item[0][1] or "")
            )
        ]
        return ctx


def build_dataset(
    data_set: EvaluationDataSet[Any, Any, Any],
    *,
    evaluators: Sequence[Evaluator],
    report_evaluators: Sequence[ReportEvaluator] = (),
    split: EvaluationSplit | None = None,
) -> Dataset[Any, Any, Any]:
    """Project a Data Set into one multi-case Pydantic Evals Dataset."""
    cases = data_set.split(split) if split is not None else data_set.cases
    if not cases:
        raise ValueError(
            f"{data_set.task} has no cases"
            + (f" in the {split.value} split" if split is not None else "")
        )
    return Dataset(
        name=data_set.task,
        cases=[_framework_case(case) for case in cases],
        evaluators=tuple(evaluators),
        report_evaluators=tuple(report_evaluators),
    )


def run_data_set(
    data_set: EvaluationDataSet[Any, Any, Any],
    *,
    task: Callable[[Any], Any],
    evaluators: Sequence[Evaluator],
    report_evaluators: Sequence[ReportEvaluator] = (),
    split: EvaluationSplit | None = None,
    max_concurrency: int = 1,
    experiment_metadata: Mapping[str, Any] | None = None,
) -> EvaluationReport[Any, Any, Any]:
    """Execute every case in ``data_set`` against ``task``.

    ``experiment_metadata`` names what the run cannot infer from the Data Set
    alone — the Model Deployment and the commit — and reaches the trace and the
    report by the same route, so the two agree by construction.
    """
    if max_concurrency < 1:
        raise ValueError("max_concurrency must be greater than 0")
    setup_telemetry()
    dataset = build_dataset(
        data_set,
        evaluators=evaluators,
        report_evaluators=report_evaluators,
        split=split,
    )
    synchronous_task = _synchronous(task)
    return dataset.evaluate_sync(
        synchronous_task,
        name=data_set.task,
        task_name=data_set.task,
        metadata=dict(experiment_metadata) if experiment_metadata else None,
        progress=False,
        max_concurrency=max_concurrency,
        lifecycle=_EvaluationCaseLifecycle,
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
