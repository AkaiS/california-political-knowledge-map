"""Canonical serialization for the immutable aggregate report input."""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from collections.abc import Mapping
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from pydantic_evals.evaluators import EvaluatorSpec
from pydantic_evals.reporting import EvaluationReport, ReportCase, ReportCaseFailure
from pydantic_evals.evaluators.evaluator import EvaluationResult

from .definitions import canonical_json


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
