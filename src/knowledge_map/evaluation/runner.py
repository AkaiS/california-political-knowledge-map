"""Coordinator for complete deterministic Evaluation Runs."""

from __future__ import annotations

import inspect
import asyncio
import hashlib
import time
from contextlib import nullcontext
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from pydantic_evals.evaluators import Evaluator, ReportEvaluator, ReportEvaluatorContext
from pydantic_evals.lifecycle import CaseLifecycle
from pydantic_evals.reporting.analyses import ScalarResult
from pydantic_evals.reporting import EvaluationReport, ReportCase, ReportCaseFailure

from .definitions import (
    EvaluationCase,
    EvaluationGoldSet,
    EvaluationRubric,
    EvaluationSplit,
    new_uuid7,
)
from .engine import EvaluationEngine
from .reporting import canonical_report_bytes, report_from_bytes
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


@dataclass
class _CancellationAwareReportEvaluator(ReportEvaluator):
    delegate: ReportEvaluator
    guard: Callable[[], None]

    def get_serialization_name(self) -> str:
        return self.delegate.get_serialization_name()

    def evaluate(self, ctx: Any) -> Any:
        self.guard()
        return self.delegate.evaluate(ctx)

    async def evaluate_async(self, ctx: Any) -> Any:
        self.guard()
        return await self.delegate.evaluate_async(ctx)


class _DurableCheckpointSink:
    """Translate framework terminal results into runner-owned ledger checkpoints."""

    def __init__(
        self,
        *,
        ledger: SQLiteEvaluationLedger,
        run: EvaluationRunRecord,
        manifest: tuple[EvaluationCaseManifestEntry, ...],
        pending_results: tuple[EvaluationCaseResult, ...],
        suite: EvaluationSuite,
        case_calls: dict[str, list[_EvaluatorCall]],
        report_calls: dict[str, list[_EvaluatorCall]],
        issues: list[EvaluationRunIssue],
        trace_id: str | None,
        span_id: str | None,
    ) -> None:
        self.ledger = ledger
        self.run = run
        self.suite = suite
        self.case_calls = case_calls
        self.report_calls = report_calls
        self.issues = issues
        self.trace_id = trace_id
        self.span_id = span_id
        self._persisted_report_call_counts = {
            configured.name: 0 for configured in suite.report_evaluators
        }
        self.results_by_name = {
            f"{entry.case_business_id}@{entry.case_revision}": result
            for entry, result in zip(manifest, pending_results)
        }
        self.configured_case_evaluators = {
            configured.name: configured for configured in suite.case_evaluators
        }

    @property
    def case_lifecycle(self) -> type[CaseLifecycle[Any, Any, Any]]:
        sink = self

        class DurableCaseLifecycle(CaseLifecycle[Any, Any, Any]):
            async def teardown(self, result: Any) -> None:
                sink.checkpoint_case(result)

        return DurableCaseLifecycle

    def checkpoint_case(self, framework_case: ReportCase[Any, Any, Any] | ReportCaseFailure[Any, Any, Any] | None) -> None:
        """Persist one terminal framework case and all evidence in one transaction."""
        if framework_case is None:
            return
        result = self.results_by_name.get(framework_case.name)
        if result is None:
            raise ValueError(f"framework returned an unknown Evaluation Case: {framework_case.name}")

        if isinstance(framework_case, ReportCaseFailure):
            exception_type, safe_message = self._split_failure_message(
                framework_case.error_message
            )
            completed = result.model_copy(
                update={
                    "execution_disposition": EvaluationCaseDisposition.FAILED,
                    "task_outcome": TaskFailure(
                        category="task_execution",
                        exception_type=exception_type,
                        safe_message=safe_message,
                        retryable=False,
                        failure_evidence={
                            "error_stacktrace": framework_case.error_stacktrace
                        },
                    ),
                }
            )
            self.ledger.record_case_evaluation(completed, (), ())
            return

        completed = result.model_copy(
            update={
                "execution_disposition": EvaluationCaseDisposition.COMPLETED,
                "task_outcome": TaskSuccess(output=framework_case.output),
            }
        )
        executions: list[CaseEvaluatorExecution] = []
        observations: list[CaseMetricObservation] = []
        for configured in self.configured_case_evaluators.values():
            calls = [
                call
                for call in self.case_calls[configured.name]
                if call.subject_name == framework_case.name
            ]
            if not calls:
                continue
            evaluator_observations: list[CaseMetricObservation] = []
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
                    trace_id=self.trace_id,
                    span_id=self.span_id,
                )
                if not call.failure_message:
                    try:
                        evaluator_observations.extend(
                            EvaluationRunner._case_observations(
                                configured,
                                call.output,
                                execution.execution_id,
                                result.result_id,
                                self.suite.metrics,
                            )
                        )
                    except Exception as exc:
                        execution = execution.model_copy(
                            update={
                                "status": EvaluationProducerStatus.FAILED,
                                "failure_message": f"{type(exc).__name__}: {exc}",
                            }
                        )
                executions.append(execution)

            produced_identities = {
                observation.metric.namespaced_name
                for observation in evaluator_observations
            }
            observations.extend(evaluator_observations)
            for metric in configured.metrics:
                if metric.namespaced_name not in produced_identities:
                    self.issues.append(
                        EvaluationRunIssue(
                            category="missing_metric",
                            subject=f"case:{framework_case.name}/{configured.name}",
                            message=f"required metric {metric.namespaced_name} was not produced",
                        )
                    )
        self.ledger.record_case_evaluation(completed, executions, observations)

    def checkpoint_report(self, report: EvaluationReport[Any, Any, Any]) -> None:
        """Freeze the exact aggregate report for explicit finalization."""
        if self.trace_id is not None:
            report.trace_id = self.trace_id
        if self.span_id is not None:
            report.span_id = self.span_id
        self.ledger.freeze_aggregate_report(
            self.run.run_id,
            canonical_report_bytes(report),
            issues=self.issues,
        )

    def checkpoint_partial_report_evidence(self) -> None:
        """Flush report evaluator calls completed before orchestration stopped."""
        self._checkpoint_report_calls()

    def _checkpoint_report_calls(self) -> None:
        for configured in self.suite.report_evaluators:
            calls = self.report_calls[configured.name]
            start = self._persisted_report_call_counts[configured.name]
            for call in calls[start:]:
                issue_start = len(self.issues)
                execution = ReportEvaluatorExecution(
                    run_id=self.run.run_id,
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
                    trace_id=self.trace_id,
                    span_id=self.span_id,
                )
                observations: list[RunMetricObservation] = []
                if not call.failure_message:
                    try:
                        observations = EvaluationRunner._run_observations(
                            configured,
                            call.output,
                            execution.execution_id,
                            self.run.run_id,
                            self.suite.metrics,
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
                        self.issues.append(
                            EvaluationRunIssue(
                                category="missing_metric",
                                subject=f"report:{configured.name}",
                                message=f"required metric {metric.namespaced_name} was not produced",
                            )
                        )
                self.ledger.record_report_evaluation(
                    [execution],
                    observations,
                    self.issues[issue_start:],
                )
                self._persisted_report_call_counts[configured.name] += 1

    @staticmethod
    def _split_failure_message(message: str) -> tuple[str, str]:
        if ": " not in message:
            return "Exception", message
        exception_type, safe_message = message.split(": ", 1)
        return exception_type, safe_message


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
        if retry_of_run_id is not None:
            if self.ledger.get_evaluation_run(retry_of_run_id) is None:
                raise KeyError(f"unknown Evaluation Run: {retry_of_run_id}")
            predecessor_manifest = self.ledger.list_evaluation_case_manifest(
                retry_of_run_id
            )
            predecessor_results = {
                result.manifest_id: result
                for result in self.ledger.list_evaluation_case_results(retry_of_run_id)
            }
            incomplete_cases = frozenset(
                (entry.case_business_id, entry.case_revision)
                for entry in predecessor_manifest
                if predecessor_results[entry.manifest_id].execution_disposition
                in {
                    EvaluationCaseDisposition.PENDING,
                    EvaluationCaseDisposition.CANCELLED,
                }
            )
            if incomplete_cases:
                def is_incomplete(case: EvaluationCase[Any, Any, Any]) -> bool:
                    return (
                        case.identity.business_id,
                        case.identity.revision,
                    ) in incomplete_cases

                if selection is None:
                    selection = is_incomplete
                elif callable(selection):
                    requested_selection = selection
                    selection = lambda case: (
                        is_incomplete(case) and requested_selection(case)
                    )
                else:
                    requested_names = frozenset(selection)
                    selection = lambda case: (
                        is_incomplete(case)
                        and case.identity.business_id in requested_names
                    )

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
        report_calls: dict[str, list[_EvaluatorCall]] = {
            configured.name: [] for configured in suite.report_evaluators
        }
        issues: list[EvaluationRunIssue] = []
        telemetry_context = _evaluation_span(run.run_id, suite.identity.business_id)
        telemetry_span = telemetry_context.__enter__()
        run_trace_id, run_span_id = _span_identity(telemetry_span)
        checkpoint_sink = _DurableCheckpointSink(
            ledger=self.ledger,
            run=run,
            manifest=manifest,
            pending_results=pending_results,
            suite=suite,
            case_calls=case_calls,
            report_calls=report_calls,
            issues=issues,
            trace_id=run_trace_id,
            span_id=run_span_id,
        )
        cancel_requested = False
        resolver_failure: Exception | None = None

        try:
            def resolve(configured: ConfiguredEvaluator) -> Evaluator | ReportEvaluator:
                nonlocal resolver_failure
                try:
                    if configured.name in report_calls:
                        cancellation_guard()
                    resolved = evaluator_resolver(configured)
                except Exception as exc:
                    resolver_failure = exc
                    raise
                if configured.name in case_calls:
                    if not isinstance(resolved, Evaluator):
                        raise ValueError(
                            f"{configured.name} did not resolve to a case evaluator"
                        )
                    return _RecordingEvaluator(
                        resolved, configured.name, case_calls[configured.name]
                    )
                if not isinstance(resolved, ReportEvaluator):
                    raise ValueError(
                        f"{configured.name} did not resolve to a report evaluator"
                    )
                return _CancellationAwareReportEvaluator(
                    _RecordingReportEvaluator(
                        resolved, configured.name, report_calls[configured.name]
                    ),
                    cancellation_guard,
                )

            def cancellation_guard() -> None:
                nonlocal cancel_requested
                if cancel_requested or (
                    should_cancel is not None and should_cancel()
                ):
                    cancel_requested = True
                    raise asyncio.CancelledError()

            def guarded_task(task_input: Any) -> Any:
                nonlocal cancel_requested
                if should_cancel is not None and should_cancel():
                    cancel_requested = True
                    raise asyncio.CancelledError()
                return task(task_input)

            evaluation_report = EvaluationEngine(checkpoint_sink).execute(
                plan=preflight.plan,
                suite=suite,
                cases=selected_cases,
                task=guarded_task,
                evaluator_resolver=resolve,
                max_concurrency=configuration.case_concurrency,
                case_lifecycle=checkpoint_sink.case_lifecycle,
                include_report_evaluators=False,
            )
            if resolver_failure is not None:
                raise resolver_failure
            completed_run = self.ledger.get_evaluation_run(run.run_id)
            if completed_run is None:  # pragma: no cover - ledger invariant
                raise KeyError(f"unknown Evaluation Run: {run.run_id}")
        except (EvaluationRunCancelled, asyncio.CancelledError):
            checkpoint_sink.checkpoint_partial_report_evidence()
            issues.append(
                EvaluationRunIssue(
                    category="cancelled", subject="run", message="run was deliberately stopped"
                )
            )
            completed_run = self.ledger.cancel_evaluation_run(run.run_id, issues=issues)
        except Exception as exc:
            if cancel_requested:
                checkpoint_sink.checkpoint_partial_report_evidence()
                issues.append(
                    EvaluationRunIssue(
                        category="cancelled",
                        subject="run",
                        message="run was deliberately stopped",
                    )
                )
                completed_run = self.ledger.cancel_evaluation_run(
                    run.run_id, issues=issues
                )
            else:
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

    def finalize(
        self,
        run_id: UUID,
        *,
        suite: EvaluationSuite | None = None,
        evaluator_resolver: Callable[[ConfiguredEvaluator], Evaluator | ReportEvaluator],
        release_gates: Mapping[str, Callable[[EvaluationRunResult], bool]] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> EvaluationRunResult:
        """Explicitly resume missing report evaluator work for one frozen run.

        ``suite`` is accepted for callers migrating from the original runner
        seam, but the persisted frozen Suite is always authoritative.
        """
        run = self.ledger.get_evaluation_run(run_id)
        if run is None:
            raise KeyError(f"unknown Evaluation Run: {run_id}")
        if run.status is EvaluationRunStatus.COMPLETED:
            return self._build_result(run, tuple(self.ledger.list_evaluation_case_manifest(run_id)))
        artifact = self.ledger.get_frozen_report_artifact(run_id)
        if artifact is None:
            raise ValueError(
                "Evaluation Finalization requires every manifested case to be terminal and the aggregate report to be frozen"
            )
        if run.status is not EvaluationRunStatus.FINALIZATION_PENDING:
            raise ValueError(
                "Evaluation Finalization requires a run in finalization_pending state"
            )

        suite = self.ledger.get_frozen_suite(run_id)
        report_bytes = self.ledger.read_artifact(artifact)
        if hashlib.sha256(report_bytes).hexdigest() != artifact.content_hash:
            raise ValueError("frozen aggregate report bytes do not match their artifact identity")
        report = report_from_bytes(report_bytes)
        existing = self.ledger.list_report_evaluator_executions(run_id)
        completed_names = {
            (execution.evaluator_name, execution.evaluator_revision,
             execution.configuration_fingerprint)
            for execution in existing
        }
        issues = list(run.issues)
        trace_id, span_id = report.trace_id, report.span_id
        for configured in suite.report_evaluators:
            if should_cancel is not None and should_cancel():
                return self._build_result(
                    run,
                    tuple(self.ledger.list_evaluation_case_manifest(run_id)),
                )
            identity = (
                configured.name,
                configured.evaluator_revision,
                configured.configuration_fingerprint,
            )
            if identity in completed_names:
                continue
            started = time.perf_counter()
            issue_start = len(issues)
            execution = ReportEvaluatorExecution(
                run_id=run_id,
                evaluator_name=configured.name,
                evaluator_revision=configured.evaluator_revision,
                configuration_fingerprint=configured.configuration_fingerprint,
                status=EvaluationProducerStatus.COMPLETED,
                duration_seconds=0,
                trace_id=trace_id,
                span_id=span_id,
            )
            observations: list[RunMetricObservation] = []
            try:
                resolved = evaluator_resolver(configured)
                if not isinstance(resolved, ReportEvaluator):
                    raise ValueError(
                        f"{configured.name} did not resolve to a report evaluator"
                    )
                output = resolved.evaluate(
                    ReportEvaluatorContext(
                        name=configured.name,
                        report=report,
                        experiment_metadata=report.experiment_metadata,
                    )
                )
                if inspect.isawaitable(output):
                    output = asyncio.run(output)
                observations = self._run_observations(
                    configured,
                    output,
                    execution.execution_id,
                    run_id,
                    suite.metrics,
                )
            except Exception as exc:
                execution = execution.model_copy(
                    update={
                        "status": EvaluationProducerStatus.FAILED,
                        "failure_message": f"{type(exc).__name__}: {exc}",
                    }
                )
            execution = execution.model_copy(
                update={"duration_seconds": time.perf_counter() - started}
            )
            produced = {observation.metric.namespaced_name for observation in observations}
            for metric in configured.metrics:
                if metric.namespaced_name not in produced:
                    issues.append(
                        EvaluationRunIssue(
                            category="missing_metric",
                            subject=f"report:{configured.name}",
                            message=f"required metric {metric.namespaced_name} was not produced",
                        )
                    )
            self.ledger.record_report_evaluation(
                [execution], observations, issues[issue_start:]
            )

        pending_run = self.ledger.get_evaluation_run(run_id)
        if pending_run is None:  # pragma: no cover - ledger invariant
            raise KeyError(f"unknown Evaluation Run: {run_id}")
        gate_outcomes: list[EvaluationGateOutcome] = []
        provisional = self._build_result(pending_run, tuple(self.ledger.list_evaluation_case_manifest(run_id)))
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
            run_id, issues=issues, gate_outcomes=gate_outcomes
        )
        return self._build_result(
            completed_run, tuple(self.ledger.list_evaluation_case_manifest(run_id))
        )

    finalize_evaluation_run = finalize

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
