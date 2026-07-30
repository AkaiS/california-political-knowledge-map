"""Shared, persistence-free execution of resolved evaluation plans."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable

from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import Evaluator, ReportEvaluator
from pydantic_evals.lifecycle import CaseLifecycle
from pydantic_evals.reporting import EvaluationReport

from .definitions import EvaluationCase
from .bindings import EvaluationTaskBinding, TaskBindingInvocationError
from .preflight import ResolvedEvaluationPlan
from .runs import TaskOutcome
from .suites import ConfiguredEvaluator, EvaluationSuite, _ConfiguredCaseEvaluator


@runtime_checkable
class EvaluationCheckpointSink(Protocol):
    """Persistence boundary exercised by both execution paths."""

    def record_task_outcome(self, task_input: Any, outcome: TaskOutcome) -> None:
        """Record the typed outcome produced by an Evaluation Task Binding."""

    @property
    def case_lifecycle(self) -> type[CaseLifecycle[Any, Any, Any]] | None:
        """Provide lifecycle notification for terminal framework cases."""

    def checkpoint_case(self, case: Any) -> None:
        """Record one terminal successful or failed framework case."""

    def checkpoint_report(self, report: EvaluationReport[Any, Any, Any]) -> None:
        """Record the aggregate report supplied to report evaluators."""

    def checkpoint_partial_report_evidence(self) -> None:
        """Record report evidence completed before orchestration stops."""


class NoOpCheckpointSink:
    """Checkpoint sink for execution that intentionally has no ledger."""

    def record_task_outcome(self, task_input: Any, outcome: TaskOutcome) -> None:
        return None

    @property
    def case_lifecycle(self) -> None:
        return None

    def checkpoint_case(self, case: Any) -> None:
        return None

    def checkpoint_report(self, report: EvaluationReport[Any, Any, Any]) -> None:
        return None

    def checkpoint_partial_report_evidence(self) -> None:
        return None


EvaluatorResolver = Callable[[ConfiguredEvaluator], Evaluator | ReportEvaluator]

class EvaluationEngine:
    """Project one frozen plan into one multi-case Pydantic Evals Dataset."""

    def __init__(self, checkpoint_sink: EvaluationCheckpointSink | None = None):
        sink = checkpoint_sink if checkpoint_sink is not None else NoOpCheckpointSink()
        if not isinstance(sink, EvaluationCheckpointSink):
            raise TypeError("checkpoint_sink must implement EvaluationCheckpointSink")
        self.checkpoint_sink = sink

    def execute(
        self,
        *,
        plan: ResolvedEvaluationPlan,
        suite: EvaluationSuite,
        cases: tuple[EvaluationCase[Any, Any, Any], ...],
        task: Callable[[Any], Any] | None = None,
        task_binding: EvaluationTaskBinding[Any, Any, Any] | None = None,
        evaluator_resolver: EvaluatorResolver,
        max_concurrency: int = 1,
    ) -> EvaluationReport[Any, Any, Any]:
        """Execute the exact case and evaluator assignments in ``plan``."""
        if (task is None) == (task_binding is None):
            raise ValueError("provide exactly one task or task_binding")
        if task_binding is not None and not task_binding.contract.is_exactly_compatible_with(suite.task_contract):
            raise ValueError("task_binding contract does not match the Suite/Gold Set contract")
        self._validate_plan_suite(plan, suite)
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be greater than 0")
        case_by_reference = {
            (case.identity.business_id, case.identity.revision): case for case in cases
        }
        selected_cases: list[EvaluationCase[Any, Any, Any]] = []
        for planned_case in plan.cases:
            key = (planned_case.case.business_id, planned_case.case.revision)
            evaluation_case = case_by_reference.get(key)
            if (
                evaluation_case is None
                or evaluation_case.content_hash != planned_case.case.content_hash
            ):
                raise ValueError(
                    "Resolved Evaluation Plan requires the exact supplied Evaluation Case revision"
                )
            selected_cases.append(evaluation_case)
        configured_by_name = {configured.name: configured for configured in suite.case_evaluators}
        suite_wide_names = tuple(
            dict.fromkeys(
                resolved.reference.name
                for planned_case in plan.cases
                for resolved in planned_case.evaluators
                if "suite-wide" in resolved.provenance
            )
        )
        suite_wide_name_set = set(suite_wide_names)
        resolved_case_names = {
            resolved.reference.name
            for planned_case in plan.cases
            for resolved in planned_case.evaluators
        }
        missing = resolved_case_names - configured_by_name.keys()
        if missing:
            raise ValueError(
                "Resolved Evaluation Plan references undeclared case evaluators: "
                + ", ".join(sorted(missing))
            )
        for planned_case in plan.cases:
            for resolved in planned_case.evaluators:
                configured = configured_by_name[resolved.reference.name]
                if resolved.reference.evaluator_revision != configured.evaluator_revision:
                    raise ValueError(
                        "Resolved Evaluation Plan references an incompatible evaluator revision: "
                        + resolved.reference.name
                    )

        evaluator_instances: dict[str, Evaluator] = {}

        def case_evaluator(name: str) -> Evaluator:
            if name not in evaluator_instances:
                resolved = evaluator_resolver(configured_by_name[name])
                if not isinstance(resolved, Evaluator):
                    raise ValueError(f"{name} did not resolve to a case evaluator")
                evaluator_instances[name] = _ConfiguredCaseEvaluator(
                    configured_by_name[name], resolved
                )
            return evaluator_instances[name]

        dataset_evaluators = tuple(case_evaluator(name) for name in suite_wide_names)
        dataset_cases = []
        for planned_case, evaluation_case in zip(plan.cases, selected_cases):
            names = dict.fromkeys(resolved.reference.name for resolved in planned_case.evaluators)
            dataset_cases.append(
                Case(
                    name=f"{planned_case.case.business_id}@{planned_case.case.revision}",
                    inputs=evaluation_case.task_input,
                    expected_output=evaluation_case.expected_output,
                    metadata=evaluation_case.metadata,
                    evaluators=tuple(
                        case_evaluator(name)
                        for name in names
                        if name not in suite_wide_name_set
                    ),
                )
            )

        dataset = Dataset(
            name=f"{suite.identity.business_id}@{suite.identity.revision}",
            cases=dataset_cases,
            evaluators=dataset_evaluators,
        )
        if task_binding is not None:
            def bound_task(task_input: Any) -> Any:
                outcome = (
                    asyncio.run(task_binding.invoke_async(task_input))
                    if task_binding.is_async
                    else task_binding.invoke(task_input)
                )
                self.checkpoint_sink.record_task_outcome(task_input, outcome)
                if outcome.kind == "failure":
                    raise TaskBindingInvocationError(outcome)
                return outcome.output

            task = bound_task
        report = dataset.evaluate_sync(
            task,
            progress=False,
            max_concurrency=max_concurrency,
            lifecycle=self.checkpoint_sink.case_lifecycle,
        )
        if self.checkpoint_sink.case_lifecycle is None:
            for case in (*report.cases, *report.failures):
                self.checkpoint_sink.checkpoint_case(case)
        self.checkpoint_sink.checkpoint_report(report)
        return report

    @staticmethod
    def _validate_plan_suite(
        plan: ResolvedEvaluationPlan, suite: EvaluationSuite
    ) -> None:
        if (
            plan.suite.business_id != suite.identity.business_id
            or plan.suite.revision != suite.identity.revision
            or plan.suite.content_hash != suite.content_hash
        ):
            raise ValueError(
                "Resolved Evaluation Plan does not belong to the supplied Evaluation Suite"
            )
