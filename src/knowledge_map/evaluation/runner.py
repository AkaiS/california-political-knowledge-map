"""Coordinator for complete deterministic Evaluation Runs."""

from __future__ import annotations

import inspect
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel
from pydantic_evals.evaluators import Evaluator, ReportEvaluator
from pydantic_evals.reporting.analyses import ScalarResult

from .definitions import EvaluationCase, EvaluationGoldSet, EvaluationSplit, new_uuid7
from .runs import (
    CaseEvaluatorExecution,
    CaseMetricObservation,
    EvaluationCaseDisposition,
    EvaluationCaseManifestEntry,
    EvaluationCaseResult,
    EvaluationProducerStatus,
    EvaluationRunConfiguration,
    EvaluationRunRecord,
    EvaluationRunResult,
    EvaluationRunStatus,
    ReportEvaluatorExecution,
    RunMetricObservation,
    TaskFailure,
    TaskSuccess,
    case_reference_map,
)
from .store import SQLiteEvaluationLedger
from .suites import (
    ConfiguredEvaluator,
    EvaluationMetricDefinition,
    EvaluationMetricReference,
    EvaluationMetricValueType,
    EvaluationSuite,
)


@dataclass
class _EvaluatorCall:
    subject_name: str
    output: Any = None
    failure_message: str | None = None
    duration_seconds: float = 0.0


@dataclass
class _RecordingEvaluator(Evaluator):
    delegate: Evaluator
    configured_name: str
    calls: list[_EvaluatorCall]

    def get_default_evaluation_name(self) -> str:
        return self.configured_name

    def evaluate(self, ctx: Any) -> Any:
        started = time.perf_counter()
        try:
            output = self.delegate.evaluate_sync(ctx)
        except Exception as exc:
            self.calls.append(
                _EvaluatorCall(
                    subject_name=ctx.name or "",
                    failure_message=f"{type(exc).__name__}: {exc}",
                    duration_seconds=time.perf_counter() - started,
                )
            )
            raise
        self.calls.append(
            _EvaluatorCall(
                subject_name=ctx.name or "",
                output=output,
                duration_seconds=time.perf_counter() - started,
            )
        )
        return output

    async def evaluate_async(self, ctx: Any) -> Any:
        started = time.perf_counter()
        try:
            output = await self.delegate.evaluate_async(ctx)
        except Exception as exc:
            self.calls.append(
                _EvaluatorCall(
                    subject_name=ctx.name or "",
                    failure_message=f"{type(exc).__name__}: {exc}",
                    duration_seconds=time.perf_counter() - started,
                )
            )
            raise
        self.calls.append(
            _EvaluatorCall(
                subject_name=ctx.name or "",
                output=output,
                duration_seconds=time.perf_counter() - started,
            )
        )
        return output


@dataclass
class _RecordingReportEvaluator(ReportEvaluator):
    delegate: ReportEvaluator
    configured_name: str
    calls: list[_EvaluatorCall]

    def get_serialization_name(self) -> str:
        return self.configured_name

    def evaluate(self, ctx: Any) -> Any:
        started = time.perf_counter()
        try:
            output = self.delegate.evaluate(ctx)
            if inspect.isawaitable(output):
                raise TypeError("async report evaluators must be resolved by evaluate_async")
        except Exception as exc:
            self.calls.append(
                _EvaluatorCall(
                    subject_name=ctx.name,
                    failure_message=f"{type(exc).__name__}: {exc}",
                    duration_seconds=time.perf_counter() - started,
                )
            )
            raise
        self.calls.append(
            _EvaluatorCall(
                subject_name=ctx.name,
                output=output,
                duration_seconds=time.perf_counter() - started,
            )
        )
        return output

    async def evaluate_async(self, ctx: Any) -> Any:
        started = time.perf_counter()
        try:
            output = await self.delegate.evaluate_async(ctx)
        except Exception as exc:
            self.calls.append(
                _EvaluatorCall(
                    subject_name=ctx.name,
                    failure_message=f"{type(exc).__name__}: {exc}",
                    duration_seconds=time.perf_counter() - started,
                )
            )
            raise
        self.calls.append(
            _EvaluatorCall(
                subject_name=ctx.name,
                output=output,
                duration_seconds=time.perf_counter() - started,
            )
        )
        return output


class EvaluationRunner:
    """Execute a typed suite and persist its complete successful evidence."""

    def __init__(self, ledger: SQLiteEvaluationLedger):
        self.ledger = ledger

    def run(
        self,
        *,
        suite: EvaluationSuite,
        gold_set: EvaluationGoldSet,
        cases: tuple[EvaluationCase[Any, Any, Any], ...],
        task: Callable[[Any], Any],
        evaluator_resolver: Callable[[ConfiguredEvaluator], Evaluator | ReportEvaluator],
        configuration: EvaluationRunConfiguration,
        selection: Callable[[EvaluationCase[Any, Any, Any]], bool]
        | Iterable[str]
        | None = None,
        selection_expression: str | None = None,
        selection_provenance: Mapping[str, Any] | None = None,
        split: EvaluationSplit | None = None,
    ) -> EvaluationRunResult:
        case_by_reference = case_reference_map(cases)
        selected_memberships = self._resolve_memberships(
            gold_set, case_by_reference, selection=selection, split=split
        )
        selected_cases = tuple(case_by_reference[(m.case.business_id, m.case.revision)] for m in selected_memberships)
        suite.validate_cases(selected_cases)

        case_records = tuple(self.ledger.import_case(case) for case in cases)
        case_record_map = {(record.business_id, record.revision): record for record in case_records}
        gold_record = self.ledger.import_gold_set(gold_set)
        suite_record = self.ledger.import_suite(suite)
        run = EvaluationRunRecord(
            suite_record_id=suite_record.record_id,
            suite_business_id=suite_record.business_id,
            suite_revision=suite_record.revision,
            suite_content_hash=suite_record.content_hash,
            gold_set_record_id=gold_record.record_id,
            gold_set_business_id=gold_record.business_id,
            gold_set_revision=gold_record.revision,
            gold_set_content_hash=gold_record.content_hash,
            configuration=configuration,
            selection_expression=selection_expression,
            selection_provenance={
                **(selection_provenance or {}),
                "resolved_case_count": len(selected_memberships),
                "resolved_case_revisions": [
                    {
                        "business_id": m.case.business_id,
                        "revision": m.case.revision,
                        "content_hash": m.case.content_hash,
                    }
                    for m in selected_memberships
                ],
            },
            status=EvaluationRunStatus.RUNNING,
        )
        manifest = tuple(
            EvaluationCaseManifestEntry(
                run_id=run.run_id,
                ordinal=index,
                case=membership.case,
                split=membership.split,
            )
            for index, membership in enumerate(selected_memberships)
        )
        pending_results = tuple(
            EvaluationCaseResult(
                run_id=run.run_id,
                manifest_id=entry.manifest_id,
                case_record_id=case_record_map[(entry.case_business_id, entry.case_revision)].record_id,
            )
            for entry in manifest
        )
        self.ledger.create_evaluation_run(run, manifest, pending_results)

        case_calls: dict[str, list[_EvaluatorCall]] = {}
        report_calls: dict[str, list[_EvaluatorCall]] = {}

        def resolve(configured: ConfiguredEvaluator) -> Evaluator | ReportEvaluator:
            resolved = evaluator_resolver(configured)
            if configured in suite.case_evaluators:
                calls: list[_EvaluatorCall] = []
                case_calls[configured.name] = calls
                return _RecordingEvaluator(resolved, configured.name, calls)  # type: ignore[arg-type]
            calls = []
            report_calls[configured.name] = calls
            return _RecordingReportEvaluator(resolved, configured.name, calls)  # type: ignore[arg-type]

        report = suite.execute(cases=selected_cases, task=task, evaluator_resolver=resolve)
        case_results: list[EvaluationCaseResult] = []
        case_executions: list[CaseEvaluatorExecution] = []
        case_observations: list[CaseMetricObservation] = []
        result_by_name = {f"{entry.case_business_id}@{entry.case_revision}": result for entry, result in zip(manifest, pending_results)}
        for report_case in report.cases:
            result = result_by_name[report_case.name]
            completed = result.model_copy(
                update={
                    "execution_disposition": EvaluationCaseDisposition.COMPLETED,
                    "task_outcome": TaskSuccess(output=report_case.output),
                }
            )
            result_executions: list[CaseEvaluatorExecution] = []
            result_observations: list[CaseMetricObservation] = []
            for configured in suite.case_evaluators:
                calls = [call for call in case_calls[configured.name] if call.subject_name == report_case.name]
                for call in calls:
                    execution = CaseEvaluatorExecution(
                        case_result_id=result.result_id,
                        evaluator_name=configured.name,
                        evaluator_revision=configured.evaluator_revision,
                        configuration_fingerprint=configured.configuration_fingerprint,
                        status=(EvaluationProducerStatus.FAILED if call.failure_message else EvaluationProducerStatus.COMPLETED),
                        duration_seconds=call.duration_seconds,
                        failure_message=call.failure_message,
                    )
                    result_executions.append(execution)
                    result_observations.extend(
                        self._case_observations(
                            configured, call.output, execution.execution_id, result.result_id, suite.metrics
                        )
                    )
            self.ledger.record_case_evaluation(completed, result_executions, result_observations)
            case_results.append(completed)
            case_executions.extend(result_executions)
            case_observations.extend(result_observations)

        report_executions: list[ReportEvaluatorExecution] = []
        run_observations: list[RunMetricObservation] = []
        for configured in suite.report_evaluators:
            for call in report_calls[configured.name]:
                execution = ReportEvaluatorExecution(
                    run_id=run.run_id,
                    evaluator_name=configured.name,
                    evaluator_revision=configured.evaluator_revision,
                    configuration_fingerprint=configured.configuration_fingerprint,
                    status=(EvaluationProducerStatus.FAILED if call.failure_message else EvaluationProducerStatus.COMPLETED),
                    duration_seconds=call.duration_seconds,
                    failure_message=call.failure_message,
                )
                report_executions.append(execution)
                run_observations.extend(
                    self._run_observations(configured, call.output, execution.execution_id, run.run_id, suite.metrics)
                )
        self.ledger.record_report_evaluation(report_executions, run_observations)
        completed_run = self.ledger.complete_evaluation_run(run.run_id)
        return EvaluationRunResult(
            run=completed_run,
            manifest=manifest,
            case_results=tuple(case_results),
            case_evaluator_executions=tuple(case_executions),
            report_evaluator_executions=tuple(report_executions),
            case_observations=tuple(case_observations),
            run_observations=tuple(run_observations),
        )

    execute = run

    @staticmethod
    def _resolve_memberships(gold_set: EvaluationGoldSet, case_by_reference: Mapping[tuple[str, int], EvaluationCase[Any, Any, Any]], *, selection: Callable[[EvaluationCase[Any, Any, Any]], bool] | Iterable[str] | None, split: EvaluationSplit | None) -> tuple[Any, ...]:
        names = set(selection) if selection is not None and not callable(selection) else None
        resolved = []
        for membership in gold_set.memberships:
            if split is not None and membership.split is not split:
                continue
            key = (membership.case.business_id, membership.case.revision)
            case = case_by_reference.get(key)
            if case is None or case.content_hash != membership.case.content_hash:
                raise ValueError("Gold Set membership requires the exact supplied case revision")
            if callable(selection) and not selection(case):
                continue
            if names is not None and membership.case.business_id not in names:
                continue
            resolved.append(membership)
        return tuple(resolved)

    @staticmethod
    def _case_observations(configured: ConfiguredEvaluator, output: Any, execution_id: Any, result_id: Any, definitions: tuple[EvaluationMetricDefinition, ...]) -> list[CaseMetricObservation]:
        return [
            CaseMetricObservation(
                case_result_id=result_id,
                case_evaluator_execution_id=execution_id,
                **EvaluationRunner._observation_fields(metric, value),
            )
            for metric, value in EvaluationRunner._metric_values(configured, output, definitions)
        ]

    @staticmethod
    def _run_observations(configured: ConfiguredEvaluator, output: Any, execution_id: Any, run_id: Any, definitions: tuple[EvaluationMetricDefinition, ...]) -> list[RunMetricObservation]:
        return [
            RunMetricObservation(
                run_id=run_id,
                report_evaluator_execution_id=execution_id,
                **EvaluationRunner._observation_fields(metric, value),
            )
            for metric, value in EvaluationRunner._metric_values(configured, output, definitions)
        ]

    @staticmethod
    def _metric_values(configured: ConfiguredEvaluator, output: Any, definitions: tuple[EvaluationMetricDefinition, ...]) -> list[tuple[EvaluationMetricDefinition, Any]]:
        if output is None or not configured.metrics:
            return []
        by_identity = {definition.identity: definition for definition in definitions}
        metrics = [by_identity[reference.namespaced_name, reference.evaluator_revision] for reference in configured.metrics]
        if isinstance(output, Mapping):
            values = []
            remaining = list(metrics)
            for key, value in output.items():
                match = next((metric for metric in remaining if metric.namespaced_name == key or metric.namespaced_name.rsplit(".", 1)[-1] == key), None)
                if match is None:
                    continue
                values.append((match, getattr(value, "value", value)))
                remaining.remove(match)
            return values
        if isinstance(output, ScalarResult):
            output = output.value
        if len(metrics) != 1:
            return []
        return [(metrics[0], output)]

    @staticmethod
    def _observation_fields(metric: EvaluationMetricDefinition, value: Any) -> dict[str, Any]:
        value = getattr(value, "value", value)
        validated = metric.validate_value(value)
        fields: dict[str, Any] = {"metric": EvaluationMetricReference.from_definition(metric)}
        if metric.value_type is EvaluationMetricValueType.NUMBER:
            fields["number_value"] = float(validated)
        elif metric.value_type is EvaluationMetricValueType.INTEGER:
            fields["integer_value"] = validated
        elif metric.value_type is EvaluationMetricValueType.BOOLEAN:
            fields["boolean_value"] = validated
        elif metric.value_type is EvaluationMetricValueType.STRING:
            fields["string_value"] = validated
        else:
            assert isinstance(validated, BaseModel)
            fields["structured_json"] = validated.model_dump(mode="json")
        return fields
