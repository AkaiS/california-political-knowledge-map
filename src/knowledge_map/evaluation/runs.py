"""Runtime contracts for deterministic evaluation runs."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Annotated, Any, Literal, Mapping
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    TypeAdapter,
    field_validator,
    model_validator,
)

from .definitions import (
    DeclaredArtifactReference,
    EvaluationCase,
    EvaluationCaseRevisionReference,
    EvaluationGoldSet,
    EvaluationSplit,
    canonical_configuration_json,
    configuration_fingerprint,
    new_uuid7,
    SchemaReference,
)
from .suites import EvaluationMetricReference


EVIDENCE_CONTRACT_VERSION = 1


def _validate_strict_json_value(value: Any, *, root: bool = False) -> Any:
    if type(value) is dict:
        if root and any(type(key) is not str for key in value):
            raise ValueError("structured metric payload object keys must be strings")
        for key, item in value.items():
            if type(key) is not str:
                raise ValueError("structured metric payload object keys must be strings")
            _validate_strict_json_value(item)
        return value
    if type(value) is list:
        for item in value:
            _validate_strict_json_value(item)
        return value
    if value is None or type(value) is str or type(value) is bool or type(value) is int:
        return value
    if type(value) is float and math.isfinite(value):
        return value
    raise ValueError("structured metric payload must contain only strict JSON values")


class StructuredMetricValue(BaseModel):
    """A durable, schema-tagged object-shaped structured metric value."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_reference: SchemaReference
    payload: dict[str, Any]

    @field_validator("payload", mode="before")
    @classmethod
    def payload_is_strict_json_object(cls, value: Any) -> Any:
        if type(value) is not dict:
            raise ValueError("structured metric payload must be a JSON object")
        return _validate_strict_json_value(value, root=True)


class EvaluationRunCancelled(Exception):
    """Raised by an injected runner control to stop a run deliberately."""


class FinalizationClaimLostError(RuntimeError):
    """Raised when an Evaluation Finalization Attempt loses its authority claim."""

    def __init__(
        self,
        claim: "EvaluationFinalizationClaim",
        *,
        last_confirmed_expiry: datetime,
        loss_classification: str,
        renewal_failure: BaseException | None = None,
    ) -> None:
        self.run_id = claim.run_id
        self.claim = claim
        self.claim_id = claim.claim_id
        self.owner_id = claim.owner_id
        self.last_confirmed_expiry = last_confirmed_expiry
        self.loss_classification = loss_classification
        self.renewal_failure = renewal_failure
        self.renewal_failure_context = (
            None
            if renewal_failure is None
            else f"{type(renewal_failure).__name__}: {renewal_failure}"
        )
        detail = f" ({self.renewal_failure_context})" if self.renewal_failure_context else ""
        super().__init__(
            "Evaluation Finalization lost its claim "
            f"for run {self.run_id} owned by {self.owner_id}: "
            f"{self.loss_classification}{detail}"
        )


class EvaluationRunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    FINALIZATION_PENDING = "finalization_pending"
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


class EvaluationFinalizationClaim(BaseModel):
    """A durable lease authorizing one worker to finalize a run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    claim_id: UUID = Field(default_factory=new_uuid7)
    run_id: UUID
    owner_id: str = Field(min_length=1)
    acquired_at: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def expires_after_acquisition(self) -> "EvaluationFinalizationClaim":
        if self.expires_at <= self.acquired_at:
            raise ValueError("finalization claim must expire after acquisition")
        return self

    def is_expired(self, now: datetime) -> bool:
        return now >= self.expires_at


class EvaluationCaseDisposition(str, Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ValidatedComponentConfiguration(BaseModel):
    """A schema-identified, canonical snapshot of component construction settings."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_reference: SchemaReference
    content: Mapping[str, Any] = Field(default_factory=dict)
    content_fingerprint: str = ""

    @classmethod
    def from_model(
        cls,
        configuration: BaseModel,
        *,
        identity: str,
        revision: int,
    ) -> "ValidatedComponentConfiguration":
        """Snapshot one validated Pydantic component configuration model."""
        if not isinstance(configuration, BaseModel):
            raise TypeError("component configuration must be a Pydantic BaseModel")
        serialized = canonical_configuration_json(configuration)
        content = json.loads(serialized)
        if not isinstance(content, dict):  # pragma: no cover - Pydantic models dump objects
            raise ValueError("component configuration must serialize to a JSON object")
        return cls(
            schema_reference=SchemaReference.for_model(
                type(configuration), identity=identity, revision=revision
            ),
            content=content,
            content_fingerprint=configuration_fingerprint(content),
        )

    from_config = from_model

    def model_post_init(self, __context: Any) -> None:
        serialized = canonical_configuration_json(self.content)
        sanitized = json.loads(serialized)
        fingerprint = configuration_fingerprint(sanitized)
        if self.content_fingerprint and self.content_fingerprint != fingerprint:
            raise ValueError(
                "content_fingerprint does not match the component configuration"
            )
        object.__setattr__(self, "content", sanitized)
        object.__setattr__(self, "content_fingerprint", fingerprint)

    @property
    def schema_identity(self) -> str:
        return self.schema_reference.identity

    @property
    def schema_revision(self) -> int:
        return self.schema_reference.revision

    @property
    def schema_fingerprint(self) -> str:
        return self.schema_reference.model_fingerprint

    @property
    def fingerprint(self) -> str:
        return self.content_fingerprint

    @property
    def configuration_fingerprint(self) -> str:
        return self.content_fingerprint


class _EmptyComponentConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _default_component_configuration() -> ValidatedComponentConfiguration:
    return ValidatedComponentConfiguration.from_model(
        _EmptyComponentConfiguration(),
        identity="knowledge-map.empty-component-configuration",
        revision=1,
    )


class EvaluationRunConfiguration(BaseModel):
    """The canonical, secret-free configuration frozen into a run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    model_parameters: Mapping[str, Any] = Field(default_factory=dict)
    execution_mode: str = Field(default="deterministic", min_length=1)
    random_seed: int | None = None
    case_concurrency: int = Field(default=1, gt=0)
    component_configuration: ValidatedComponentConfiguration = Field(
        default_factory=_default_component_configuration
    )
    code_fingerprint: str | None = None
    configuration_json: str = ""
    content_fingerprint: str = ""

    def model_post_init(self, __context: Any) -> None:
        effective = {
            "provider": self.provider,
            "model": self.model,
            "model_parameters": self.model_parameters,
            "execution_mode": self.execution_mode,
            "random_seed": self.random_seed,
            "case_concurrency": self.case_concurrency,
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
        object.__setattr__(self, "model_parameters", sanitized["model_parameters"])

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


class ReportCaseEvaluatorSourceEvidence(BaseModel):
    """Canonical evaluator constructor identity persisted in ReportCase evidence."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1)
    arguments: tuple[Any, ...] | Mapping[str, Any] | None = None


class ReportCaseScoreEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1)
    value: int | float
    reason: str | None = None
    source: ReportCaseEvaluatorSourceEvidence
    evaluator_version: str | None = None


class ReportCaseLabelEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1)
    value: str
    reason: str | None = None
    source: ReportCaseEvaluatorSourceEvidence
    evaluator_version: str | None = None


class ReportCaseAssertionEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1)
    value: StrictBool
    reason: str | None = None
    source: ReportCaseEvaluatorSourceEvidence
    evaluator_version: str | None = None


class ReportCaseEvaluatorFailureEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1)
    error_message: str
    error_stacktrace: str
    source: ReportCaseEvaluatorSourceEvidence
    evaluator_version: str | None = None
    error_type: str | None = None


class SuccessfulReportCaseEvidence(BaseModel):
    """Evidence-contract-v1 projection of a successful framework ReportCase."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["success"] = "success"
    name: str = Field(min_length=1)
    output: Any
    metrics: Mapping[str, int | float] = Field(default_factory=dict)
    attributes: Mapping[str, Any] = Field(default_factory=dict)
    scores: Mapping[str, ReportCaseScoreEvidence] = Field(default_factory=dict)
    labels: Mapping[str, ReportCaseLabelEvidence] = Field(default_factory=dict)
    assertions: Mapping[str, ReportCaseAssertionEvidence] = Field(
        default_factory=dict
    )
    evaluator_failures: tuple[ReportCaseEvaluatorFailureEvidence, ...] = ()
    task_duration: float = Field(ge=0)
    total_duration: float = Field(ge=0)
    source_case_name: str | None = None
    trace_id: str | None = None
    span_id: str | None = None

    @model_validator(mode="after")
    def total_includes_task_duration(self) -> "SuccessfulReportCaseEvidence":
        if self.total_duration < self.task_duration:
            raise ValueError(
                "total_duration must be greater than or equal to task_duration"
            )
        return self


class FailedReportCaseEvidence(BaseModel):
    """Evidence-contract-v1 projection of a failed framework ReportCase."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["failure"] = "failure"
    name: str = Field(min_length=1)
    error_message: str
    error_stacktrace: str
    source_case_name: str | None = None
    trace_id: str | None = None
    span_id: str | None = None


ReportCaseEvidence = Annotated[
    SuccessfulReportCaseEvidence | FailedReportCaseEvidence,
    Field(discriminator="kind"),
]
REPORT_CASE_EVIDENCE_ADAPTER = TypeAdapter(ReportCaseEvidence)


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
    frozen_aggregate_manifest_artifact_id: UUID | None = None
    finalization_claim: EvaluationFinalizationClaim | None = None

    @property
    def configuration_json(self) -> str:
        return self.configuration.configuration_json

    @property
    def aggregate_manifest_artifact_id(self) -> UUID | None:
        return self.frozen_aggregate_manifest_artifact_id


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
    checkpoint_id: UUID | None = None
    checkpoint_content_hash: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )


class FrozenAggregateManifestEntry(BaseModel):
    """Integrity references for one terminal case, without copied case evidence."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ordinal: int = Field(ge=0)
    manifest_entry_id: UUID
    manifest_entry_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    case_result_id: UUID
    case_result_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    checkpoint_id: UUID
    checkpoint_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class FrozenAggregateManifest(BaseModel):
    """Canonical composition of immutable run definitions and terminal evidence."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: UUID
    suite_record_id: UUID
    suite_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    resolved_plan_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    task_contract_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_contract_version: int = Field(ge=1)
    report_provenance: Mapping[str, Any]
    cases: tuple[FrozenAggregateManifestEntry, ...]

    @property
    def canonical_bytes(self) -> bytes:
        return json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")


class EvaluationMetricObservation(BaseModel):
    """One metric value with exactly one typed persisted representation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    observation_id: UUID = Field(default_factory=new_uuid7)
    metric: EvaluationMetricReference
    number_value: float | None = None
    integer_value: int | None = None
    boolean_value: bool | None = None
    string_value: str | None = None
    structured_value: StructuredMetricValue | None = None

    @model_validator(mode="after")
    def has_exactly_one_value(self) -> "EvaluationMetricObservation":
        values = (
            self.number_value,
            self.integer_value,
            self.boolean_value,
            self.string_value,
            self.structured_value,
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
            self.structured_value,
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
