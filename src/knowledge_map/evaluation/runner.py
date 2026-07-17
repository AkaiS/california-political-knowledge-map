"""Coordinator for complete deterministic Evaluation Runs."""

from __future__ import annotations

import inspect
import asyncio
import time
from contextlib import nullcontext
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import Evaluator, ReportEvaluator
from pydantic_evals.evaluators import ReportEvaluatorContext
from pydantic_evals.reporting.analyses import ScalarResult
from pydantic_evals.reporting import EvaluationReport

from .definitions import (
    EvaluationCase,
    EvaluationGoldSet,
    EvaluationRubric,
    EvaluationSplit,
    new_uuid7,
)
from .preflight import EvaluationPreflightError, preflight_selected_cases
from .runs import (
    CaseEvaluatorExecution,
    CaseMetricObservation,
    EvaluationCaseDisposition,
    EvaluationCaseManifestEntry,
    EvaluationCaseResult,
    EvaluationProducerStatus,
    EvaluationRunConfiguration,
    EvaluationGateOutcome,
    EvaluationRunIssue,
    EvaluationRunRecord,
    EvaluationRunResult,
    EvaluationRunStatus,
    ReportEvaluatorExecution,
    RunMetricObservation,
    TaskFailure,
    EvaluationRunCancelled,
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

try:
    import logfire
except ImportError:  # pragma: no cover - dependency is optional at this seam
    logfire = None


def _evaluation_span(run_id: UUID, suite_business_id: str):
    if logfire is None:
        return nullcontext()
    try:
        return logfire.span(
            "evaluation_run",
            run_id=str(run_id),
            suite_business_id=suite_business_id,
        )
    except Exception:
        return nullcontext()


def _span_identity(span: Any) -> tuple[str | None, str | None]:
    try:
        context = span.get_span_context()
        trace_id = context.trace_id
        span_id = context.span_id
        normalized_trace = (
            None
            if trace_id in (None, 0)
            else f"{trace_id:032x}" if isinstance(trace_id, int) else str(trace_id)
        )
        normalized_span = (
            None
            if span_id in (None, 0)
            else f"{span_id:016x}" if isinstance(span_id, int) else str(span_id)
        )
        return normalized_trace, normalized_span
    except Exception:
        return None, None


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
        rubrics: tuple[EvaluationRubric, ...] = (),
        task: Callable[[Any], Any],
        evaluator_resolver: Callable[[ConfiguredEvaluator], Evaluator | ReportEvaluator],
        configuration: EvaluationRunConfiguration,
        selection: Callable[[EvaluationCase[Any, Any, Any]], bool]
        | Iterable[str]
        | None = None,
        selection_expression: str | None = None,
        selection_provenance: Mapping[str, Any] | None = None,
        split: EvaluationSplit | None = None,
        retry_of_run_id: UUID | None = None,
        should_cancel: Callable[[], bool] | None = None,
        release_gates: Mapping[str, Callable[[EvaluationRunResult], bool]] | None = None,
    ) -> EvaluationRunResult:
        preflight = preflight_selected_cases(
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            selection=selection,
            split=split,
        )
        if not preflight.is_compatible:
            raise EvaluationPreflightError(preflight)

        case_by_reference = case_reference_map(cases)
        assert preflight.plan is not None
        memberships_by_key = {
            (membership.case.business_id, membership.case.revision): membership
            for membership in gold_set.memberships
        }
        selected_memberships = tuple(
            memberships_by_key[(planned.case.business_id, planned.case.revision)]
            for planned in preflight.plan.cases
        )
        selected_cases = tuple(
            case_by_reference[(m.case.business_id, m.case.revision)]
            for m in selected_memberships
        )
        suite.validate_cases(selected_cases)

        case_records = tuple(self.ledger.import_case(case) for case in cases)
        case_record_map = {
            (record.business_id, record.revision): record for record in case_records
        }
        manifested_case_records = tuple(
            case_record_map[(membership.case.business_id, membership.case.revision)]
            for membership in selected_memberships
        )
        gold_record = self.ledger.import_gold_set(gold_set)
        suite_record = self.ledger.import_suite(suite)
        expected_rubrics = {
            (reference.record_id, reference.content_hash)
            for reference in suite.rubrics
        }
        supplied_rubrics = {
            (rubric.identity.record_id, rubric.content_hash) for rubric in rubrics
        }
        if expected_rubrics != supplied_rubrics:
            raise ValueError(
                "runner requires the exact authored Evaluation Rubric revisions "
                "declared by the suite"
            )
        rubric_records = tuple(self.ledger.import_rubric(rubric) for rubric in rubrics)
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
            retry_of_run_id=retry_of_run_id,
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
                case_record_id=case_record_map[
                    (entry.case_business_id, entry.case_revision)
                ].record_id,
            )
            for entry in manifest
        )
        self.ledger.create_evaluation_run(
            run=run,
            plan=preflight.plan,
            manifest=manifest,
            pending_results=pending_results,
        )
        for record in (
            suite_record,
            gold_record,
            *manifested_case_records,
            *rubric_records,
        ):
            for artifact_link in self.ledger.list_definition_artifacts(record.record_id):
                self.ledger.link_consumed_artifact_to_run(
                    run.run_id,
                    artifact_link.artifact_id,
                    role=artifact_link.role,
                )

        case_calls: dict[str, list[_EvaluatorCall]] = {
            configured.name: [] for configured in suite.case_evaluators
        }
        report_cases: list[Any] = []
        report_failures: list[Any] = []
        issues: list[EvaluationRunIssue] = []
        result_by_name = {
            f"{entry.case_business_id}@{entry.case_revision}": result
            for entry, result in zip(manifest, pending_results)
        }
        telemetry_context = _evaluation_span(run.run_id, suite.identity.business_id)
        telemetry_span = telemetry_context.__enter__()
        run_trace_id, run_span_id = _span_identity(telemetry_span)

        try:
            for entry, evaluation_case in zip(manifest, selected_cases):
                if should_cancel is not None and should_cancel():
                    raise EvaluationRunCancelled()

                def resolve_case(configured: ConfiguredEvaluator) -> Evaluator:
                    resolved = evaluator_resolver(configured)
                    if not isinstance(resolved, Evaluator):
                        raise ValueError(
                            f"{configured.name} did not resolve to a case evaluator"
                        )
                    return _RecordingEvaluator(
                        resolved, configured.name, case_calls[configured.name]
                    )

                evaluators = [
                    resolve_case(configured) for configured in suite.case_evaluators
                ]
                dataset = Dataset(
                    name=f"{suite.identity.business_id}@{suite.identity.revision}",
                    cases=[
                        Case(
                            name=f"{entry.case_business_id}@{entry.case_revision}",
                            inputs=evaluation_case.task_input,
                            expected_output=evaluation_case.expected_output,
                            metadata=evaluation_case.metadata,
                        )
                    ],
                    evaluators=evaluators,
                )
                report = dataset.evaluate_sync(
                    task, progress=False, max_concurrency=1
                )
                result = result_by_name[
                    f"{entry.case_business_id}@{entry.case_revision}"
                ]
                if report.failures:
                    failed_case = report.failures[0]
                    report_failures.append(failed_case)
                    completed = result.model_copy(
                        update={
                            "execution_disposition": EvaluationCaseDisposition.FAILED,
                            "task_outcome": TaskFailure(
                                category="task_execution",
                                exception_type=failed_case.error_message.split(":", 1)[0],
                                safe_message=self._safe_error_message(
                                    failed_case.error_message
                                ),
                                retryable=False,
                                failure_evidence={
                                    "error_stacktrace": failed_case.error_stacktrace
                                },
                            ),
                        }
                    )
                    self.ledger.record_case_evaluation(completed, (), ())
                    continue

                if len(report.cases) != 1:
                    raise RuntimeError("single-case evaluation returned no case result")
                report_case = report.cases[0]
                report_cases.append(report_case)
                result_executions: list[CaseEvaluatorExecution] = []
                result_observations: list[CaseMetricObservation] = []
                completed = result.model_copy(
                    update={
                        "execution_disposition": EvaluationCaseDisposition.COMPLETED,
                        "task_outcome": TaskSuccess(output=report_case.output),
                    }
                )
                for configured in suite.case_evaluators:
                    calls = [
                        call
                        for call in case_calls[configured.name]
                        if call.subject_name == report_case.name
                    ]
                    for call in calls:
                        execution = CaseEvaluatorExecution(
                            case_result_id=result.result_id,
                            evaluator_name=configured.name,
                            evaluator_revision=configured.evaluator_revision,
                            configuration_fingerprint=configured.configuration_fingerprint,
                            status=(
                                EvaluationProducerStatus.FAILED
                                if call.failure_message
                                else EvaluationProducerStatus.COMPLETED
                            ),
                            duration_seconds=call.duration_seconds,
                            failure_message=call.failure_message,
                            trace_id=run_trace_id,
                            span_id=run_span_id,
                        )
                        result_executions.append(execution)
                        if not call.failure_message:
                            try:
                                result_observations.extend(
                                    self._case_observations(
                                        configured,
                                        call.output,
                                        execution.execution_id,
                                        result.result_id,
                                        suite.metrics,
                                    )
                                )
                            except Exception as exc:
                                result_executions[-1] = execution.model_copy(
                                    update={
                                        "status": EvaluationProducerStatus.FAILED,
                                        "failure_message": f"{type(exc).__name__}: {exc}",
                                    }
                                )
                        produced_identities = {
                            observation.metric.namespaced_name
                            for observation in result_observations
                        }
                        for metric in configured.metrics:
                            if metric.namespaced_name not in produced_identities:
                                issues.append(
                                    EvaluationRunIssue(
                                        category="missing_metric",
                                        subject=f"case:{entry.case_business_id}@{entry.case_revision}/{configured.name}",
                                        message=f"required metric {metric.namespaced_name} was not produced",
                                    )
                                )
                self.ledger.record_case_evaluation(
                    completed, result_executions, result_observations
                )

            if should_cancel is not None and should_cancel():
                raise EvaluationRunCancelled()

            evaluation_report = EvaluationReport(
                name=f"{suite.identity.business_id}@{suite.identity.revision}",
                cases=report_cases,
                failures=report_failures,
            )
            report_ctx = ReportEvaluatorContext(
                name=evaluation_report.name,
                report=evaluation_report,
                experiment_metadata=None,
            )
            report_calls: dict[str, list[_EvaluatorCall]] = {
                configured.name: [] for configured in suite.report_evaluators
            }
            for configured in suite.report_evaluators:
                if should_cancel is not None and should_cancel():
                    raise EvaluationRunCancelled()
                calls = report_calls[configured.name]
                try:
                    resolved = evaluator_resolver(configured)
                    if not isinstance(resolved, ReportEvaluator):
                        raise ValueError(
                            f"{configured.name} did not resolve to a report evaluator"
                        )
                    recording = _RecordingReportEvaluator(
                        resolved, configured.name, calls
                    )
                    asyncio.run(recording.evaluate_async(report_ctx))
                except Exception as exc:
                    if not calls:
                        calls.append(
                            _EvaluatorCall(
                                subject_name=evaluation_report.name,
                                failure_message=f"{type(exc).__name__}: {exc}",
                            )
                        )
                for call in calls:
                    execution = ReportEvaluatorExecution(
                        run_id=run.run_id,
                        evaluator_name=configured.name,
                        evaluator_revision=configured.evaluator_revision,
                        configuration_fingerprint=configured.configuration_fingerprint,
                        status=(
                            EvaluationProducerStatus.FAILED
                            if call.failure_message
                            else EvaluationProducerStatus.COMPLETED
                        ),
                        duration_seconds=call.duration_seconds,
                        failure_message=call.failure_message,
                        trace_id=run_trace_id,
                        span_id=run_span_id,
                    )
                    observations: list[RunMetricObservation] = []
                    if not call.failure_message:
                        try:
                            observations = self._run_observations(
                                configured,
                                call.output,
                                execution.execution_id,
                                run.run_id,
                                suite.metrics,
                            )
                        except Exception as exc:
                            execution = execution.model_copy(
                                update={
                                    "status": EvaluationProducerStatus.FAILED,
                                    "failure_message": f"{type(exc).__name__}: {exc}",
                                }
                            )
                    produced_identities = {
                        observation.metric.namespaced_name for observation in observations
                    }
                    for metric in configured.metrics:
                        if metric.namespaced_name not in produced_identities:
                            issues.append(
                                EvaluationRunIssue(
                                    category="missing_metric",
                                    subject=f"report:{configured.name}",
                                    message=f"required metric {metric.namespaced_name} was not produced",
                                )
                            )
                    self.ledger.record_report_evaluation([execution], observations)

            gate_outcomes: list[EvaluationGateOutcome] = []
            provisional = self._build_result(run, manifest)
            for gate_name, gate in (release_gates or {}).items():
                try:
                    passed = bool(gate(provisional))
                    failure_message = None if passed else "release gate did not pass"
                except Exception as exc:
                    passed = False
                    failure_message = f"{type(exc).__name__}: {exc}"
                gate_outcomes.append(
                    EvaluationGateOutcome(
                        gate_name=gate_name,
                        passed=passed,
                        failure_message=failure_message,
                    )
                )
                if not passed:
                    issues.append(
                        EvaluationRunIssue(
                            category="gate_failure",
                            subject=gate_name,
                            message=failure_message or "release gate did not pass",
                        )
                    )
            completed_run = self.ledger.complete_evaluation_run(
                run.run_id, issues=issues, gate_outcomes=gate_outcomes
            )
        except EvaluationRunCancelled:
            issues.append(
                EvaluationRunIssue(
                    category="cancelled", subject="run", message="run was deliberately stopped"
                )
            )
            completed_run = self.ledger.cancel_evaluation_run(run.run_id, issues=issues)
        except Exception as exc:
            issues.append(
                EvaluationRunIssue(
                    category="orchestration_failure",
                    subject="run",
                    message=f"{type(exc).__name__}: {exc}",
                )
            )
            completed_run = self.ledger.fail_evaluation_run(run.run_id, issues=issues)
        finally:
            telemetry_context.__exit__(None, None, None)

        return self._build_result(completed_run, manifest)

    execute = run

    def _build_result(
        self, run: EvaluationRunRecord, manifest: tuple[EvaluationCaseManifestEntry, ...]
    ) -> EvaluationRunResult:
        case_results = tuple(self.ledger.list_case_results(run.run_id))
        case_executions = tuple(
            execution
            for result in case_results
            for execution in self.ledger.list_case_evaluator_executions(result.result_id)
        )
        return EvaluationRunResult(
            run=run,
            manifest=manifest,
            case_results=case_results,
            case_evaluator_executions=case_executions,
            report_evaluator_executions=tuple(
                self.ledger.list_report_evaluator_executions(run.run_id)
            ),
            case_observations=tuple(
                observation
                for result in case_results
                for observation in self.ledger.list_case_metric_observations(result.result_id)
            ),
            run_observations=tuple(
                self.ledger.list_run_metric_observations(run.run_id)
            ),
        )

    @staticmethod
    def _safe_error_message(message: str) -> str:
        return message.split(": ", 1)[1] if ": " in message else message

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
