"""Deterministic projections of evaluator-visible report evidence."""

from __future__ import annotations

import asyncio
import inspect
import json
import time
from dataclasses import asdict, dataclass, is_dataclass
from collections.abc import Callable, Iterable, Iterator, Mapping
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from pydantic_evals.evaluators import (
    EvaluatorFailure,
    EvaluatorSpec,
    ReportEvaluator,
    ReportEvaluatorContext,
)
from pydantic_evals.reporting import EvaluationReport, ReportCase, ReportCaseFailure
from pydantic_evals.evaluators.evaluator import EvaluationResult

from .definitions import SchemaReference, canonical_json


@dataclass(frozen=True)
class ReportEvaluatorCall:
    """One portable report-evaluator execution before evidence persistence."""

    configured: Any
    output: Any = None
    failure_message: str | None = None
    duration_seconds: float = 0.0


def iter_report_evaluator_calls(
    *,
    report: EvaluationReport[Any, Any, Any],
    configured_evaluators: Iterable[Any],
    evaluator_resolver: Callable[[Any], Any],
    completed_identities: Iterable[tuple[str, int, str]] = (),
    guard: Callable[[], None] = lambda: None,
    should_stop: Callable[[], bool] | None = None,
) -> Iterator[ReportEvaluatorCall]:
    """Invoke configured report evaluators identically for every execution path."""
    completed = set(completed_identities)
    for configured in configured_evaluators:
        guard()
        if should_stop is not None and should_stop():
            return
        identity = (
            configured.name,
            configured.evaluator_revision,
            configured.configuration_fingerprint,
        )
        if identity in completed:
            continue

        guard()
        started = time.perf_counter()
        output = None
        failure_message = None
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
        except Exception as exc:
            failure_message = f"{type(exc).__name__}: {exc}"
        guard()
        yield ReportEvaluatorCall(
            configured=configured,
            output=output,
            failure_message=failure_message,
            duration_seconds=time.perf_counter() - started,
        )


class SchemaRegistry:
    """Allowlist exact authored schema contracts to concrete Pydantic models."""

    def __init__(self) -> None:
        self._models: dict[tuple[str, int, str], type[BaseModel]] = {}

    def register(
        self, reference: SchemaReference | None, model_type: type[BaseModel]
    ) -> None:
        if reference is None:
            raise ValueError("a schema reference is required")
        actual = SchemaReference.for_model(
            model_type, identity=reference.identity, revision=reference.revision
        )
        if actual != reference:
            raise ValueError("registered model does not match the exact schema fingerprint")
        self._models[self._key(reference)] = model_type

    def resolve(self, reference: SchemaReference) -> type[BaseModel]:
        try:
            return self._models[self._key(reference)]
        except KeyError as exc:
            raise ValueError(
                f"schema is not allowlisted: {reference.identity}@{reference.revision}"
            ) from exc

    def resolve_binding(self, reference: SchemaReference) -> "ResolvedSchemaBinding":
        """Resolve an authored schema reference to its allowlisted model type."""
        return ResolvedSchemaBinding(
            expected_reference=reference,
            model_type=self.resolve(reference),
        )

    def validate(self, reference: SchemaReference, value: Any) -> BaseModel:
        return self.resolve(reference).model_validate(value)

    @staticmethod
    def _key(reference: SchemaReference) -> tuple[str, int, str]:
        return (
            reference.identity,
            reference.revision,
            reference.model_fingerprint,
        )


@dataclass(frozen=True)
class ResolvedSchemaBinding:
    """One exact schema reference paired with its allowlisted runtime model."""

    expected_reference: SchemaReference
    model_type: type[BaseModel]

    def __post_init__(self) -> None:
        actual = SchemaReference.for_model(
            self.model_type,
            identity=self.expected_reference.identity,
            revision=self.expected_reference.revision,
        )
        if actual != self.expected_reference:
            raise ValueError(
                "resolved schema binding model does not match the exact schema fingerprint"
            )


def materialize_structured_metric_observation(
    observation: Any, binding: ResolvedSchemaBinding
) -> BaseModel:
    """Reconstruct one fetched structured metric observation without persistence access."""
    structured_value = getattr(observation, "structured_value", None)
    if structured_value is None:
        raise ValueError("materialization requires a structured metric observation")
    if structured_value.schema_reference != binding.expected_reference:
        raise ValueError("structured metric observation schema tag does not match binding")
    return binding.model_type.model_validate(structured_value.payload)


def materialize_metric_observation(
    observation: Any, *, suite: Any, schemas: SchemaRegistry
) -> Any:
    """Materialize one observation using the frozen Suite's metric definition."""
    if getattr(observation, "structured_value", None) is None:
        return observation.value
    binding = suite.resolve_structured_metric_binding(observation.metric, schemas)
    return materialize_structured_metric_observation(observation, binding)


def _json_value(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _json_value(value.model_dump(mode="json"))
    if is_dataclass(value) and not isinstance(value, type):
        return _json_value(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_value(item) for item in value]
    if isinstance(value, Enum):
        return _json_value(value.value)
    if isinstance(value, UUID):
        return str(value)
    return value


def canonical_report_bytes(report: EvaluationReport[Any, Any, Any]) -> bytes:
    """Serialize one report to deterministic bytes for content addressing."""
    payload = {
        "name": report.name,
        "cases": report.cases,
        "failures": report.failures,
        "experiment_metadata": report.experiment_metadata,
        "trace_id": report.trace_id,
        "span_id": report.span_id,
    }
    return canonical_json(_json_value(payload)).encode("utf-8")


def report_case_payload(
    case: ReportCase[Any, Any, Any] | ReportCaseFailure[Any, Any, Any]
) -> dict[str, Any]:
    """Return canonical run evidence, excluding immutable authored values."""
    payload = _json_value(case)
    for authored_field in ("inputs", "metadata", "expected_output"):
        payload.pop(authored_field, None)
    payload["kind"] = "failure" if isinstance(case, ReportCaseFailure) else "success"
    return payload


def evaluator_version_tag(revision: int, configuration_fingerprint: str) -> str:
    """Project the configured evaluator's single behavioral identity."""
    return f"revision-{revision}:{configuration_fingerprint}"


def _evaluation_result(value: Any) -> EvaluationResult[Any]:
    source = value.get("source", {})
    return EvaluationResult(
        name=value["name"],
        value=value["value"],
        reason=value.get("reason"),
        source=EvaluatorSpec(
            name=source.get("name", "frozen-evaluation-report"),
            arguments=source.get("arguments"),
        ),
        evaluator_version=value.get("evaluator_version"),
    )


def _evaluator_failure(value: Any) -> EvaluatorFailure:
    source = value.get("source", {})
    return EvaluatorFailure(
        name=value["name"],
        error_message=value["error_message"],
        error_stacktrace=value["error_stacktrace"],
        source=EvaluatorSpec(
            name=source["name"],
            arguments=source.get("arguments"),
        ),
        evaluator_version=value.get("evaluator_version"),
        error_type=value.get("error_type"),
    )


def report_from_bytes(content: bytes) -> EvaluationReport[Any, Any, Any]:
    """Load the report input without consulting mutable authored definitions."""
    payload = json.loads(content)
    cases = []
    for raw in payload["cases"]:
        cases.append(
            ReportCase(
                name=raw["name"],
                inputs=raw["inputs"],
                metadata=raw.get("metadata"),
                expected_output=raw.get("expected_output"),
                output=raw["output"],
                metrics=raw.get("metrics", {}),
                attributes=raw.get("attributes", {}),
                scores={
                    name: _evaluation_result(result)
                    for name, result in raw.get("scores", {}).items()
                },
                labels={
                    name: _evaluation_result(result)
                    for name, result in raw.get("labels", {}).items()
                },
                assertions={
                    name: _evaluation_result(result)
                    for name, result in raw.get("assertions", {}).items()
                },
                task_duration=raw.get("task_duration", 0),
                total_duration=raw.get("total_duration", 0),
                source_case_name=raw.get("source_case_name"),
                trace_id=raw.get("trace_id"),
                span_id=raw.get("span_id"),
            )
        )
    failures = [ReportCaseFailure(**raw) for raw in payload.get("failures", [])]
    return EvaluationReport(
        name=payload["name"],
        cases=cases,
        failures=failures,
        experiment_metadata=payload.get("experiment_metadata"),
        trace_id=payload.get("trace_id"),
        span_id=payload.get("span_id"),
    )
