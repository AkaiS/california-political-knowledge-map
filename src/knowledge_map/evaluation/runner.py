"""Coordinator for complete deterministic Evaluation Runs."""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import sqlite3
import threading
import time
from contextlib import nullcontext
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
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
from .bindings import EvaluationTaskBinding
from .reporting import (
    SchemaRegistry,
    report_case_payload,
)
from .preflight import EvaluationPreflightError, preflight_selected_cases
from .runs import (
    CaseEvaluatorExecution,
    CaseMetricObservation,
    EvaluationCaseDisposition,
    EvaluationCaseManifestEntry,
    EvaluationCaseResult,
    EvaluationFinalizationClaim,
    EvaluationProducerStatus,
    EvaluationRunConfiguration,
    EvaluationGateOutcome,
    EvaluationRunIssue,
    EvaluationRunRecord,
    EvaluationRunResult,
    EvaluationRunStatus,
    ReportEvaluatorExecution,
    RunMetricObservation,
    StructuredMetricValue,
    TaskFailure,
    TaskOutcome,
    EvaluationRunCancelled,
    FinalizationClaimLostError,
    TaskSuccess,
    case_reference_map,
)
from .store import EvaluationLedger
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


logger = logging.getLogger(__name__)


def _task_input_key(value: Any) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _emit_finalization_telemetry(event: str, **fields: Any) -> None:
    """Emit operational finalization events without making telemetry mandatory."""
    logger.info("evaluation_finalization.%s", event, extra=fields)
    if logfire is None:
        return
    try:
        logfire.info(f"evaluation_finalization.{event}", **fields)
    except Exception:
        logger.debug("failed to emit finalization telemetry", exc_info=True)


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


def _record_sync_call(
    calls: list[_EvaluatorCall], subject_name: str, operation: Callable[[], Any]
) -> Any:
    started = time.perf_counter()
    try:
        output = operation()
    except Exception as exc:
        calls.append(
            _EvaluatorCall(
                subject_name=subject_name,
                failure_message=f"{type(exc).__name__}: {exc}",
                duration_seconds=time.perf_counter() - started,
            )
        )
        raise
    calls.append(
        _EvaluatorCall(
            subject_name=subject_name,
            output=output,
            duration_seconds=time.perf_counter() - started,
        )
    )
    return output


async def _record_async_call(
    calls: list[_EvaluatorCall], subject_name: str, operation: Callable[[], Any]
) -> Any:
    started = time.perf_counter()
    try:
        output = await operation()
    except Exception as exc:
        calls.append(
            _EvaluatorCall(
                subject_name=subject_name,
                failure_message=f"{type(exc).__name__}: {exc}",
                duration_seconds=time.perf_counter() - started,
            )
        )
        raise
    calls.append(
        _EvaluatorCall(
            subject_name=subject_name,
            output=output,
            duration_seconds=time.perf_counter() - started,
        )
    )
    return output


@dataclass
class _RecordingEvaluator(Evaluator):
    delegate: Evaluator
    configured_name: str
    calls: list[_EvaluatorCall]

    def get_default_evaluation_name(self) -> str:
        return self.configured_name

    def evaluate(self, ctx: Any) -> Any:
        return _record_sync_call(
            self.calls,
            ctx.name or "",
            lambda: self.delegate.evaluate_sync(ctx),
        )

    async def evaluate_async(self, ctx: Any) -> Any:
        return await _record_async_call(
            self.calls,
            ctx.name or "",
            lambda: self.delegate.evaluate_async(ctx),
        )


@dataclass
class _RecordingReportEvaluator(ReportEvaluator):
    delegate: ReportEvaluator
    configured_name: str
    calls: list[_EvaluatorCall]

    def get_serialization_name(self) -> str:
        return self.configured_name

    def evaluate(self, ctx: Any) -> Any:
        def invoke() -> Any:
            output = self.delegate.evaluate(ctx)
            if inspect.isawaitable(output):
                raise TypeError("async report evaluators must be resolved by evaluate_async")
            return output

        return _record_sync_call(self.calls, ctx.name, invoke)

    async def evaluate_async(self, ctx: Any) -> Any:
        return await _record_async_call(
            self.calls,
            ctx.name,
            lambda: self.delegate.evaluate_async(ctx),
        )


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


@dataclass(frozen=True)
class _FinalizationClaimLoss:
    classification: str
    last_confirmed_expiry: datetime
    renewal_failure: BaseException | None = None


def _is_retryable_sqlite_contention(exc: BaseException) -> bool:
    """Recognize only SQLite's explicit busy/locked write contention errors."""
    if not isinstance(exc, sqlite3.OperationalError):
        return False
    error_code = getattr(exc, "sqlite_errorcode", None)
    retryable_codes = {
        getattr(sqlite3, "SQLITE_BUSY", None),
        getattr(sqlite3, "SQLITE_LOCKED", None),
    }
    if error_code in retryable_codes - {None}:
        return True
    message = str(exc).casefold()
    return "busy" in message or "locked" in message


class _FinalizationHeartbeat:
    """Renew one finalization claim independently of report work."""

    def __init__(
        self,
        ledger: EvaluationLedger,
        run_id: UUID,
        claim: EvaluationFinalizationClaim,
        lease_seconds: float,
    ) -> None:
        self._ledger = ledger
        self._run_id = run_id
        self._claim = claim
        self._lease_seconds = lease_seconds
        self._stop = threading.Event()
        self._loss_lock = threading.Lock()
        self._state_changed = threading.Condition(self._loss_lock)
        self._loss: _FinalizationClaimLoss | None = None
        self._authority_unknown = False
        self._completion_in_flight = False
        self._completion_confirmed = False
        self._last_confirmed_expiry = claim.expires_at
        self._thread = threading.Thread(
            target=self._run,
            name=f"evaluation-finalization-heartbeat:{claim.claim_id}",
            daemon=True,
        )

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        with self._state_changed:
            self._state_changed.notify_all()
        self._thread.join()

    def confirm_completion(self) -> None:
        """Stop renewal once the ledger has durably completed the run."""
        with self._state_changed:
            self._completion_in_flight = False
            self._completion_confirmed = True
            self._authority_unknown = False
            self._stop.set()
            self._state_changed.notify_all()

    def begin_completion(self) -> None:
        """Mark the current attempt's fenced completion transaction as in flight."""
        with self._state_changed:
            self._completion_in_flight = True

    def abort_completion(self) -> None:
        """Allow ordinary claim-loss handling after a failed completion attempt."""
        with self._state_changed:
            self._completion_in_flight = False
            self._state_changed.notify_all()

    @property
    def loss(self) -> _FinalizationClaimLoss | None:
        with self._state_changed:
            return self._loss

    @property
    def run_id(self) -> UUID:
        return self._run_id

    @property
    def claim_id(self) -> UUID:
        return self._claim.claim_id

    @property
    def lease_seconds(self) -> float:
        return self._lease_seconds

    def wait_for_retry(self, delay_seconds: float) -> bool:
        """Wait using the heartbeat stop signal; return whether stopping was requested."""
        return self._stop.wait(delay_seconds)

    @property
    def last_confirmed_expiry(self) -> datetime:
        with self._state_changed:
            return self._last_confirmed_expiry

    def wait_until_authority_confirmed(self) -> None:
        """Pause finalization until a transient renewal uncertainty resolves."""
        with self._state_changed:
            while self._authority_unknown and self._loss is None and not self._stop.is_set():
                self._state_changed.wait()
            loss = self._loss
        if loss is not None:
            raise self.claim_loss_error()

    def claim_loss_error(self) -> FinalizationClaimLostError:
        loss = self.loss
        if loss is None:  # pragma: no cover - caller invariant
            raise RuntimeError("finalization claim loss has not been recorded")
        return FinalizationClaimLostError(
            self._claim,
            last_confirmed_expiry=loss.last_confirmed_expiry,
            loss_classification=loss.classification,
            renewal_failure=loss.renewal_failure,
        )

    def record_loss(
        self,
        classification: str,
        renewal_failure: BaseException | None = None,
    ) -> None:
        with self._state_changed:
            if self._loss is not None or self._completion_confirmed:
                return
            last_confirmed_expiry = self._last_confirmed_expiry
            self._loss = _FinalizationClaimLoss(
                classification=classification,
                last_confirmed_expiry=last_confirmed_expiry,
                renewal_failure=renewal_failure,
            )
            self._authority_unknown = False
            self._state_changed.notify_all()
        _emit_finalization_telemetry(
            "claim_lost",
            run_id=str(self._run_id),
            claim_id=str(self._claim.claim_id),
            owner_id=self._claim.owner_id,
            loss_classification=classification,
            last_confirmed_expiry=last_confirmed_expiry.isoformat(),
            renewal_failure=(
                None
                if renewal_failure is None
                else f"{type(renewal_failure).__name__}: {renewal_failure}"
            ),
        )

    def record_transient_renewal_failure(
        self, exc: BaseException, retry_delay_seconds: float
    ) -> None:
        with self._state_changed:
            if (
                self._loss is not None
                or self._completion_confirmed
                or self._stop.is_set()
            ):
                return
            self._authority_unknown = True
            last_confirmed_expiry = self._last_confirmed_expiry
        _emit_finalization_telemetry(
            "renewal_transient_failure",
            run_id=str(self._run_id),
            claim_id=str(self._claim.claim_id),
            owner_id=self._claim.owner_id,
            last_confirmed_expiry=last_confirmed_expiry.isoformat(),
            retry_delay_seconds=retry_delay_seconds,
            renewal_failure=f"{type(exc).__name__}: {exc}",
        )

    def _now(self) -> datetime:
        current = self._ledger.clock()
        if current.tzinfo is None:
            raise ValueError("finalization heartbeat timestamps must include a timezone")
        return current.astimezone(timezone.utc)

    def _record_expiry_loss_if_needed(self) -> bool:
        if self._now() < self.last_confirmed_expiry:
            return False
        if not self._stop.is_set():
            self.record_loss("claim_expired")
        return True

    def _claim_is_still_live(self) -> bool:
        if self._record_expiry_loss_if_needed():
            return False
        try:
            owns_claim = self._ledger.owns_finalization_claim(
                self._run_id, self._claim.claim_id
            )
        except Exception as exc:
            if _is_retryable_sqlite_contention(exc):
                return not self._record_expiry_loss_if_needed()
            if not self._stop.is_set():
                self.record_loss("renewal_failure", exc)
            return False
        if self._record_expiry_loss_if_needed():
            return False
        if owns_claim:
            return True
        if not self._stop.is_set():
            self.record_loss(self.classify_claim_loss())
        return False

    def classify_claim_loss(self) -> str:
        try:
            current = self._ledger.get_finalization_claim(self._run_id)
            if current is None:
                return "claim_cleared"
            if current.claim_id != self._claim.claim_id:
                return "claim_replaced"
            if not self._ledger.owns_finalization_claim(
                self._run_id, self._claim.claim_id
            ):
                return "claim_expired"
        except Exception:
            return "claim_not_live"
        return "claim_not_live"

    def _run_completion_is_confirmed(self) -> bool:
        with self._state_changed:
            return self._completion_in_flight or self._completion_confirmed

    def _run(self) -> None:
        cadence = self._lease_seconds / 3
        retry_delay = min(1.0, max(0.001, cadence / 4))
        while not self._stop.is_set():
            try:
                renewed = self._ledger.renew_finalization_claim(
                    self._run_id,
                    self._claim.claim_id,
                    lease_seconds=self._lease_seconds,
                )
            except Exception as exc:
                if self._stop.is_set():
                    return
                if not _is_retryable_sqlite_contention(exc):
                    if self._run_completion_is_confirmed():
                        return
                    self.record_loss("renewal_failure", exc)
                    return
                self.record_transient_renewal_failure(exc, retry_delay)
                if not self._claim_is_still_live():
                    return
                if self._stop.wait(retry_delay):
                    return
                if not self._claim_is_still_live():
                    return
                retry_delay = min(1.0, retry_delay * 2)
                continue
            if self._stop.is_set():
                return
            if renewed is None:
                if self._run_completion_is_confirmed():
                    return
                self.record_loss(self.classify_claim_loss())
                return
            with self._state_changed:
                self._last_confirmed_expiry = renewed.expires_at
                self._authority_unknown = False
                self._state_changed.notify_all()
            _emit_finalization_telemetry(
                "claim_renewed",
                run_id=str(self._run_id),
                claim_id=str(self._claim.claim_id),
                owner_id=self._claim.owner_id,
                expires_at=renewed.expires_at.isoformat(),
            )
            if self._stop.wait(cadence):
                return


class _DurableCheckpointSink:
    """Translate framework terminal results into runner-owned ledger checkpoints."""

    def __init__(
        self,
        *,
        ledger: EvaluationLedger,
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
        self._task_outcomes: dict[str, list[TaskOutcome]] = {}

    def record_task_outcome(self, task_input: Any, outcome: TaskOutcome) -> None:
        """Hold Binding evidence until its complete case checkpoint is written."""
        self._task_outcomes.setdefault(_task_input_key(task_input), []).append(outcome)

    def _take_task_outcome(self, task_input: Any) -> TaskOutcome | None:
        outcomes = self._task_outcomes.get(_task_input_key(task_input))
        if not outcomes:
            return None
        outcome = outcomes.pop(0)
        if not outcomes:
            self._task_outcomes.pop(_task_input_key(task_input), None)
        return outcome

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

        bound_outcome = self._take_task_outcome(framework_case.inputs)
        if isinstance(framework_case, ReportCaseFailure):
            if isinstance(bound_outcome, TaskFailure):
                completed = result.model_copy(
                    update={
                        "execution_disposition": EvaluationCaseDisposition.FAILED,
                        "task_outcome": bound_outcome,
                    }
                )
                self.ledger.record_case_evaluation(
                    completed, (), (), report_case_payload(framework_case)
                )
                return
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
            self.ledger.record_case_evaluation(
                completed, (), (), report_case_payload(framework_case)
            )
            return

        success = (
            bound_outcome
            if isinstance(bound_outcome, TaskSuccess)
            else TaskSuccess(output=framework_case.output)
        )
        completed = result.model_copy(
            update={
                "execution_disposition": EvaluationCaseDisposition.COMPLETED,
                "task_outcome": success,
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
        evidence = report_case_payload(framework_case)
        self.ledger.record_case_evaluation(
            completed, executions, observations, evidence
        )

    def checkpoint_report(self, report: EvaluationReport[Any, Any, Any]) -> None:
        """Freeze the report's exact checkpoint composition for finalization."""
        if self.trace_id is not None:
            report.trace_id = self.trace_id
        if self.span_id is not None:
            report.span_id = self.span_id
        self.ledger.freeze_aggregate_manifest(
            self.run.run_id,
            issues=self.issues,
            report_provenance={
                "report_name": report.name,
                "experiment_metadata": report.experiment_metadata,
                "trace_id": report.trace_id,
                "span_id": report.span_id,
            },
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

    def __init__(self, ledger: EvaluationLedger):
        self.ledger = ledger

    def run(
        self,
        *,
        suite: EvaluationSuite,
        gold_set: EvaluationGoldSet,
        cases: tuple[EvaluationCase[Any, Any, Any], ...],
        rubrics: tuple[EvaluationRubric, ...] = (),
        evaluator_resolver: Callable[[ConfiguredEvaluator], Evaluator | ReportEvaluator],
        configuration: EvaluationRunConfiguration,
        task: Callable[[Any], Any] | None = None,
        task_binding: EvaluationTaskBinding[Any, Any, Any] | None = None,
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
        if (task is None) == (task_binding is None):
            raise ValueError("provide exactly one task or task_binding")
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
        gold_set.validate_cases(selected_cases)
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
                if task_binding is not None:
                    outcome = (
                        asyncio.run(task_binding.invoke_async(task_input))
                        if task_binding.is_async
                        else task_binding.invoke(task_input)
                    )
                    checkpoint_sink.record_task_outcome(task_input, outcome)
                    if outcome.kind == "failure":
                        raise RuntimeError(outcome.safe_message)
                    return outcome.output
                assert task is not None
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
        schemas: SchemaRegistry,
        evaluator_resolver: Callable[[ConfiguredEvaluator], Evaluator | ReportEvaluator],
        release_gates: Mapping[str, Callable[[EvaluationRunResult], bool]] | None = None,
        should_stop_finalization: Callable[[], bool] | None = None,
        worker_id: str | None = None,
        lease_seconds: float = 300.0,
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
        artifact = self.ledger.get_frozen_aggregate_manifest_artifact(run_id)
        if artifact is None:
            raise ValueError(
                "Evaluation Finalization requires every manifested case to be terminal and the aggregate manifest to be frozen"
            )
        if run.status is not EvaluationRunStatus.FINALIZATION_PENDING:
            raise ValueError(
                "Evaluation Finalization requires a run in finalization_pending state"
            )

        owner_id = worker_id or f"evaluation-finalizer:{new_uuid7()}"
        claim = self.ledger.acquire_finalization_claim(
            run_id,
            owner_id=owner_id,
            lease_seconds=lease_seconds,
        )
        if claim is None:
            current_claim = self.ledger.get_finalization_claim(run_id)
            if current_claim is None:  # pragma: no cover - ledger invariant
                raise RuntimeError("finalization claim was not acquired")
            raise RuntimeError(
                "Evaluation Finalization is protected by a live finalization claim "
                f"owned by {current_claim.owner_id} until {current_claim.expires_at.isoformat()}"
            )

        heartbeat = _FinalizationHeartbeat(
            self.ledger, run_id, claim, lease_seconds
        )
        heartbeat.start()
        try:
            self._finalize_with_claim(
                run_id,
                claim=claim,
                heartbeat=heartbeat,
                schemas=schemas,
                evaluator_resolver=evaluator_resolver,
                release_gates=release_gates,
                should_stop_finalization=should_stop_finalization,
            )
        finally:
            heartbeat.stop()
            try:
                self.ledger.release_finalization_claim(run_id, claim.claim_id)
            except Exception as exc:
                _emit_finalization_telemetry(
                    "claim_release_failed",
                    run_id=str(run_id),
                    claim_id=str(claim.claim_id),
                    owner_id=claim.owner_id,
                    error=f"{type(exc).__name__}: {exc}",
                )

        released_run = self.ledger.get_evaluation_run(run_id)
        if released_run is None:  # pragma: no cover - ledger invariant
            raise KeyError(f"unknown Evaluation Run: {run_id}")
        return self._build_result(
            released_run, tuple(self.ledger.list_evaluation_case_manifest(run_id))
        )

    def _finalize_with_claim(
        self,
        run_id: UUID,
        *,
        claim: EvaluationFinalizationClaim,
        heartbeat: _FinalizationHeartbeat,
        schemas: SchemaRegistry,
        evaluator_resolver: Callable[[ConfiguredEvaluator], Evaluator | ReportEvaluator],
        release_gates: Mapping[str, Callable[[EvaluationRunResult], bool]] | None,
        should_stop_finalization: Callable[[], bool] | None,
    ) -> EvaluationRunResult:
        """Perform report work while holding one finalization claim."""

        run = self.ledger.get_evaluation_run(run_id)
        if run is None:  # pragma: no cover - ledger invariant
            raise KeyError(f"unknown Evaluation Run: {run_id}")
        suite = self.ledger.get_frozen_suite(run_id)
        artifact = self.ledger.get_frozen_aggregate_manifest_artifact(run_id)
        if artifact is None:  # pragma: no cover - ledger invariant
            raise ValueError("Evaluation Finalization has no frozen aggregate manifest")
        report = self.ledger.materialize_aggregate_report(run_id, schemas)
        existing = self.ledger.list_report_evaluator_executions(run_id)
        completed_names = {
            (execution.evaluator_name, execution.evaluator_revision,
             execution.configuration_fingerprint)
            for execution in existing
        }
        issues = list(run.issues)
        trace_id, span_id = report.trace_id, report.span_id
        for configured in suite.report_evaluators:
            self._ensure_finalization_claim(heartbeat)
            if should_stop_finalization is not None and should_stop_finalization():
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
            self._ensure_finalization_claim(heartbeat)
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
                    suite.metrics,
                )
            except Exception as exc:
                execution = execution.model_copy(
                    update={
                        "status": EvaluationProducerStatus.FAILED,
                        "failure_message": f"{type(exc).__name__}: {exc}",
                    }
                )
            self._ensure_finalization_claim(heartbeat)
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
            self._retry_finalization_persistence(
                lambda: self.ledger.record_report_evaluation(
                    [execution],
                    observations,
                    issues[issue_start:],
                    finalization_claim_id=claim.claim_id,
                ),
                heartbeat,
                operation_name="report_checkpoint",
            )

        pending_run = self.ledger.get_evaluation_run(run_id)
        if pending_run is None:  # pragma: no cover - ledger invariant
            raise KeyError(f"unknown Evaluation Run: {run_id}")
        gate_outcomes: list[EvaluationGateOutcome] = []
        provisional = self._build_result(pending_run, tuple(self.ledger.list_evaluation_case_manifest(run_id)))
        for gate_name, gate in (release_gates or {}).items():
            self._ensure_finalization_claim(heartbeat)
            if should_stop_finalization is not None and should_stop_finalization():
                return self._build_result(
                    run,
                    tuple(self.ledger.list_evaluation_case_manifest(run_id)),
                )
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
            self._ensure_finalization_claim(heartbeat)
        self._ensure_finalization_claim(heartbeat)
        heartbeat.begin_completion()
        try:
            completed_run = self._retry_finalization_persistence(
                lambda: self.ledger.complete_evaluation_run(
                    run_id,
                    issues=issues,
                    gate_outcomes=gate_outcomes,
                    finalization_claim_id=claim.claim_id,
                ),
                heartbeat,
                operation_name="completion",
            )
        except Exception:
            heartbeat.abort_completion()
            raise
        heartbeat.confirm_completion()
        return self._build_result(
            completed_run, tuple(self.ledger.list_evaluation_case_manifest(run_id))
        )

    def _retry_finalization_persistence(
        self,
        attempt: Callable[[], Any],
        heartbeat: _FinalizationHeartbeat,
        *,
        operation_name: str,
    ) -> Any:
        """Retry only transient SQLite contention while the claim remains live."""
        delay = min(1.0, max(0.001, heartbeat.lease_seconds / 12))
        while True:
            try:
                return attempt()
            except Exception as exc:
                if not _is_retryable_sqlite_contention(exc):
                    raise
                if operation_name == "completion":
                    run = self.ledger.get_evaluation_run(heartbeat.run_id)
                    if run is not None and run.status is EvaluationRunStatus.COMPLETED:
                        return run
                self._ensure_finalization_claim(heartbeat)
                _emit_finalization_telemetry(
                    "persistence_transient_failure",
                    run_id=str(heartbeat.run_id),
                    claim_id=str(heartbeat.claim_id),
                    operation=operation_name,
                    retry_delay_seconds=delay,
                    error=f"{type(exc).__name__}: {exc}",
                )
                if heartbeat.wait_for_retry(delay):
                    raise heartbeat.claim_loss_error()
                self._ensure_finalization_claim(heartbeat)
                delay = min(1.0, delay * 2)

    def _ensure_finalization_claim(
        self, heartbeat: _FinalizationHeartbeat
    ) -> None:
        heartbeat.wait_until_authority_confirmed()
        if heartbeat.loss is not None:
            raise heartbeat.claim_loss_error()
        if self.ledger.owns_finalization_claim(
            heartbeat.run_id, heartbeat.claim_id
        ):
            return
        heartbeat.record_loss(heartbeat.classify_claim_loss())
        raise heartbeat.claim_loss_error()

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
    def _case_observations(configured: ConfiguredEvaluator, output: Any, execution_id: Any, definitions: tuple[EvaluationMetricDefinition, ...]) -> list[CaseMetricObservation]:
        return [
            CaseMetricObservation(
                case_evaluator_execution_id=execution_id,
                **EvaluationRunner._observation_fields(metric, value),
            )
            for metric, value in EvaluationRunner._metric_values(configured, output, definitions)
        ]

    @staticmethod
    def _run_observations(configured: ConfiguredEvaluator, output: Any, execution_id: Any, definitions: tuple[EvaluationMetricDefinition, ...]) -> list[RunMetricObservation]:
        return [
            RunMetricObservation(
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
            fields["structured_value"] = StructuredMetricValue(
                schema_reference=metric.structured_schema,
                payload=validated.model_dump(mode="json"),
            )
        return fields
