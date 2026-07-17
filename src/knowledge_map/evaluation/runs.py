"""Runtime contracts for deterministic evaluation runs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Literal, Mapping
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .definitions import (
    DeclaredArtifactReference,
    EvaluationCase,
    EvaluationCaseRevisionReference,
    EvaluationGoldSet,
    EvaluationSplit,
    canonical_configuration_json,
    configuration_fingerprint,
    new_uuid7,
)
from .suites import EvaluationMetricReference


class EvaluationRunCancelled(Exception):
    """Raised by an injected runner control to stop a run deliberately."""


class EvaluationRunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class EvaluationProducerStatus(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"


class EvaluationRunIssue(BaseModel):
    """A quality or lifecycle diagnostic independent of run completion."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    category: str = Field(min_length=1)
    subject: str = Field(min_length=1)
    message: str = Field(min_length=1)


class EvaluationGateOutcome(BaseModel):
    """The result of a release policy check, separate from workflow status."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    gate_name: str = Field(min_length=1)
    passed: bool
    failure_message: str | None = None


class EvaluationCaseDisposition(str, Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class EvaluationRunConfiguration(BaseModel):
    """The canonical, secret-free configuration frozen into a run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    execution_mode: str = Field(default="deterministic", min_length=1)
    random_seed: int | None = None
    case_concurrency: int = Field(default=1, gt=0)
    model_settings: Mapping[str, Any] = Field(default_factory=dict)
    component_configuration: Mapping[str, Any] = Field(default_factory=dict)
    code_fingerprint: str | None = None
    configuration_json: str = ""
    content_fingerprint: str = ""

    def model_post_init(self, __context: Any) -> None:
        effective = {
            "provider": self.provider,
            "model": self.model,
            "execution_mode": self.execution_mode,
            "random_seed": self.random_seed,
            "case_concurrency": self.case_concurrency,
            "model_settings": self.model_settings,
            "component_configuration": self.component_configuration,
            "code_fingerprint": self.code_fingerprint,
        }
        serialized = canonical_configuration_json(effective)
        fingerprint = configuration_fingerprint(effective)
        if self.configuration_json and self.configuration_json != serialized:
            raise ValueError("configuration_json does not match the effective configuration")
        if self.content_fingerprint and self.content_fingerprint != fingerprint:
            raise ValueError("content_fingerprint does not match the effective configuration")
        object.__setattr__(self, "configuration_json", serialized)
        object.__setattr__(self, "content_fingerprint", fingerprint)
        sanitized = json.loads(serialized)
        object.__setattr__(self, "model_settings", sanitized["model_settings"])
        object.__setattr__(self, "component_configuration", sanitized["component_configuration"])

    @property
    def configuration_fingerprint(self) -> str:
        return self.content_fingerprint


class TaskSuccess(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["success"] = "success"
    output: Any
    artifacts: tuple[DeclaredArtifactReference, ...] = ()

    @model_validator(mode="before")
    @classmethod
    def accept_output_artifact_vocabulary(cls, value: Any) -> Any:
        if isinstance(value, dict) and "output_artifacts" in value:
            value = dict(value)
            value["artifacts"] = value.pop("output_artifacts")
        return value

    @property
    def output_artifacts(self) -> tuple[DeclaredArtifactReference, ...]:
        return self.artifacts


class TaskFailure(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["failure"] = "failure"
    category: str = Field(min_length=1)
    exception_type: str = Field(min_length=1)
    safe_message: str = Field(min_length=1)
    retryable: bool = False
    failure_evidence: Mapping[str, Any] = Field(default_factory=dict)
    artifacts: tuple[DeclaredArtifactReference, ...] = ()

    @model_validator(mode="before")
    @classmethod
    def accept_failure_artifact_vocabulary(cls, value: Any) -> Any:
        if isinstance(value, dict) and "failure_artifacts" in value:
            value = dict(value)
            value["artifacts"] = value.pop("failure_artifacts")
        return value

    @property
    def failure_artifacts(self) -> tuple[DeclaredArtifactReference, ...]:
        return self.artifacts


TaskOutcome = TaskSuccess | TaskFailure


class EvaluationRunRecord(BaseModel):
    """The immutable identity and frozen inputs of one run attempt."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: UUID = Field(default_factory=new_uuid7)
    suite_record_id: UUID
    suite_business_id: str = Field(min_length=1)
    suite_revision: int = Field(ge=1)
    suite_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    gold_set_record_id: UUID
    gold_set_business_id: str = Field(min_length=1)
    gold_set_revision: int = Field(ge=1)
    gold_set_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    configuration: EvaluationRunConfiguration
    selection_expression: str | None = None
    selection_provenance: Mapping[str, Any] = Field(default_factory=dict)
    status: EvaluationRunStatus = EvaluationRunStatus.PENDING
    retry_of_run_id: UUID | None = None
    issues: tuple[EvaluationRunIssue, ...] = ()
    gate_outcomes: tuple[EvaluationGateOutcome, ...] = ()

    @property
    def configuration_json(self) -> str:
        return self.configuration.configuration_json


class EvaluationCaseManifestEntry(BaseModel):
    """One authoritative exact case revision in a frozen run population."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    manifest_id: UUID = Field(default_factory=new_uuid7)
    run_id: UUID
    ordinal: int = Field(ge=0)
    case: EvaluationCaseRevisionReference
    split: EvaluationSplit

    @property
    def case_record_id(self) -> UUID:
        return self.case.record_id

    @property
    def case_business_id(self) -> str:
        return self.case.business_id

    @property
    def case_revision(self) -> int:
        return self.case.revision

    @property
    def case_content_hash(self) -> str:
        return self.case.content_hash


class EvaluationCaseResult(BaseModel):
    """A result envelope that exists even while its task is pending."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    result_id: UUID = Field(default_factory=new_uuid7)
    run_id: UUID
    manifest_id: UUID
    case_record_id: UUID
    execution_disposition: EvaluationCaseDisposition = EvaluationCaseDisposition.PENDING
    task_outcome: TaskOutcome | None = None


class EvaluationMetricObservation(BaseModel):
    """One metric value with exactly one typed persisted representation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    observation_id: UUID = Field(default_factory=new_uuid7)
    metric: EvaluationMetricReference
    number_value: float | None = None
    integer_value: int | None = None
    boolean_value: bool | None = None
    string_value: str | None = None
    structured_json: Any | None = None

    @model_validator(mode="after")
    def has_exactly_one_value(self) -> "EvaluationMetricObservation":
        values = (
            self.number_value,
            self.integer_value,
            self.boolean_value,
            self.string_value,
            self.structured_json,
        )
        if sum(value is not None for value in values) != 1:
            raise ValueError("a metric observation must contain exactly one value")
        return self

    @property
    def value(self) -> Any:
        for value in (
            self.number_value,
            self.integer_value,
            self.boolean_value,
            self.string_value,
            self.structured_json,
        ):
            if value is not None:
                return value
        raise AssertionError("validated observation has no value")


class CaseMetricObservation(EvaluationMetricObservation):
    case_result_id: UUID
    case_evaluator_execution_id: UUID


class RunMetricObservation(EvaluationMetricObservation):
    run_id: UUID
    report_evaluator_execution_id: UUID


class CaseEvaluatorExecution(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    execution_id: UUID = Field(default_factory=new_uuid7)
    case_result_id: UUID
    evaluator_name: str = Field(min_length=1)
    evaluator_revision: int = Field(ge=1)
    configuration_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: EvaluationProducerStatus
    duration_seconds: float = Field(ge=0)
    failure_message: str | None = None
    trace_id: str | None = None
    span_id: str | None = None


class ReportEvaluatorExecution(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    execution_id: UUID = Field(default_factory=new_uuid7)
    run_id: UUID
    evaluator_name: str = Field(min_length=1)
    evaluator_revision: int = Field(ge=1)
    configuration_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: EvaluationProducerStatus
    duration_seconds: float = Field(ge=0)
    failure_message: str | None = None
    trace_id: str | None = None
    span_id: str | None = None


@dataclass(frozen=True)
class EvaluationRunResult:
    run: EvaluationRunRecord
    manifest: tuple[EvaluationCaseManifestEntry, ...]
    case_results: tuple[EvaluationCaseResult, ...]
    case_evaluator_executions: tuple[CaseEvaluatorExecution, ...]
    report_evaluator_executions: tuple[ReportEvaluatorExecution, ...]
    case_observations: tuple[CaseMetricObservation, ...]
    run_observations: tuple[RunMetricObservation, ...]

    @property
    def results(self) -> tuple[EvaluationCaseResult, ...]:
        return self.case_results

    @property
    def evaluation_run(self) -> EvaluationRunRecord:
        return self.run


def case_reference_map(
    cases: tuple[EvaluationCase[Any, Any, Any], ...],
) -> dict[tuple[str, int], EvaluationCase[Any, Any, Any]]:
    return {
        (case.identity.business_id, case.identity.revision): case
        for case in cases
    }


def jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return value


def json_dumps(value: Any) -> str:
    return json.dumps(jsonable(value), sort_keys=True, separators=(",", ":"))


# Domain vocabulary aliases keep callers independent from the persistence
# suffix used by the record models.
EvaluationRun = EvaluationRunRecord
EvaluationCaseManifest = EvaluationCaseManifestEntry
