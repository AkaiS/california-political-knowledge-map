"""Executable evaluation-suite and metric contracts."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import Evaluator, ReportEvaluator
from pydantic_evals.reporting import EvaluationReport

from .definitions import (
    EvaluationCase,
    EvaluationRubric,
    SchemaReference,
    canonical_configuration_json,
    configuration_fingerprint,
    content_fingerprint,
    new_uuid7,
)
from uuid import UUID


_RUNTIME_EXECUTION_SETTING_KEYS = frozenset(
    {"provider", "model", "provider_settings", "model_settings"}
)


class EvaluationMetricValueType(str, Enum):
    """The persisted value shape declared by an Evaluation Metric Definition."""

    NUMBER = "number"
    INTEGER = "integer"
    BOOLEAN = "boolean"
    STRING = "string"
    STRUCTURED = "structured"


class EvaluationComparisonResult(str, Enum):
    BETTER = "better"
    EQUIVALENT = "equivalent"
    WORSE = "worse"
    INCOMPARABLE = "incomparable"


class NoComparisonOperation(BaseModel):
    """An explicitly non-comparable metric semantics."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    namespaced_name: str = Field(
        pattern=r"^[a-z][a-z0-9-]*(?:\.[a-z][a-z0-9-]*)+$"
    )
    revision: int = Field(ge=1)

    @property
    def identity(self) -> tuple[str, int]:
        return (self.namespaced_name, self.revision)

    def compare(self, *, candidate: Any, baseline: Any) -> EvaluationComparisonResult:
        return EvaluationComparisonResult.INCOMPARABLE


class OrderedComparisonOperation(BaseModel):
    """A revisioned ordering shared by scalar metric values."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    namespaced_name: str = Field(
        pattern=r"^[a-z][a-z0-9-]*(?:\.[a-z][a-z0-9-]*)+$"
    )
    revision: int = Field(ge=1)
    higher_is_better: bool

    @property
    def identity(self) -> tuple[str, int]:
        return (self.namespaced_name, self.revision)

    def compare(
        self, *, candidate: float | int, baseline: float | int
    ) -> EvaluationComparisonResult:
        if candidate == baseline:
            return EvaluationComparisonResult.EQUIVALENT
        candidate_is_better = candidate > baseline
        if candidate_is_better is self.higher_is_better:
            return EvaluationComparisonResult.BETTER
        return EvaluationComparisonResult.WORSE


class CustomComparisonOperation(BaseModel):
    """A serialized reference to comparison logic owned by an evaluator."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    namespaced_name: str = Field(
        pattern=r"^[a-z][a-z0-9-]*(?:\.[a-z][a-z0-9-]*)+$"
    )
    revision: int = Field(ge=1)
    configuration: Mapping[str, Any] = Field(default_factory=dict)

    @property
    def identity(self) -> tuple[str, int]:
        return (self.namespaced_name, self.revision)


class EvaluationMetricDefinition(BaseModel):
    """The stable, revisioned meaning of one evaluation measurement."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    namespaced_name: str = Field(pattern=r"^[a-z][a-z0-9-]*(?:\.[a-z][a-z0-9-]*)+$")
    evaluator_revision: int = Field(ge=1)
    value_type: EvaluationMetricValueType
    structured_schema: SchemaReference | None = None
    semantic_description: str = Field(min_length=1)
    comparison_operation: (
        OrderedComparisonOperation | NoComparisonOperation | CustomComparisonOperation
    )

    @model_validator(mode="after")
    def structured_value_type_has_an_exact_schema(self) -> "EvaluationMetricDefinition":
        if self.value_type is EvaluationMetricValueType.STRUCTURED:
            if self.structured_schema is None:
                raise ValueError("structured metrics require a structured_schema")
        elif self.structured_schema is not None:
            raise ValueError("only structured metrics may declare a structured_schema")
        return self

    @property
    def identity(self) -> tuple[str, int]:
        """The business identity of this immutable metric revision."""
        return (self.namespaced_name, self.evaluator_revision)

    def validate_value(self, value: Any) -> BaseModel | float | int | bool | str:
        """Validate a scalar observation against this metric's declared value type."""
        if self.value_type is EvaluationMetricValueType.NUMBER:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError("number metric values must be numbers")
        elif self.value_type is EvaluationMetricValueType.INTEGER:
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError("integer metric values must be integers")
        elif self.value_type is EvaluationMetricValueType.BOOLEAN:
            if not isinstance(value, bool):
                raise ValueError("boolean metric values must be booleans")
        elif self.value_type is EvaluationMetricValueType.STRING:
            if not isinstance(value, str):
                raise ValueError("string metric values must be strings")
        else:
            if not isinstance(value, BaseModel):
                raise ValueError("structured metric values must be Pydantic models")
            assert self.structured_schema is not None
            value_schema = content_fingerprint(type(value).model_json_schema())
            if value_schema != self.structured_schema.model_fingerprint:
                raise ValueError(
                    "structured metric values must match their exact Pydantic schema"
                )
        return value

    def compare(
        self,
        *,
        candidate: Any,
        baseline: Any,
        custom_comparator: Callable[
            [Any, Any, CustomComparisonOperation], EvaluationComparisonResult
        ]
        | None = None,
    ) -> EvaluationComparisonResult:
        candidate_value = self.validate_value(candidate)
        baseline_value = self.validate_value(baseline)
        if isinstance(self.comparison_operation, CustomComparisonOperation):
            if custom_comparator is None:
                return EvaluationComparisonResult.INCOMPARABLE
            return custom_comparator(
                candidate_value, baseline_value, self.comparison_operation
            )
        return self.comparison_operation.compare(
            candidate=candidate_value, baseline=baseline_value
        )


class EvaluationSuiteIdentity(BaseModel):
    """The opaque and business identifiers for one immutable suite revision."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    record_id: UUID = Field(default_factory=new_uuid7)
    business_id: str = Field(min_length=1)
    revision: int = Field(ge=1)


class EvaluationRubricRevisionReference(BaseModel):
    """A content-addressed reference to the exact Evaluation Rubric revision."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    record_id: UUID
    business_id: str = Field(min_length=1)
    revision: int = Field(ge=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def from_rubric(cls, rubric: EvaluationRubric) -> "EvaluationRubricRevisionReference":
        return cls(
            record_id=rubric.identity.record_id,
            business_id=rubric.identity.business_id,
            revision=rubric.identity.revision,
            content_hash=rubric.content_hash,
        )


class EvaluationTaskContract(BaseModel):
    """The exact typed inputs, outputs, and metadata accepted by a suite task."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    input_schema: SchemaReference
    output_schema: SchemaReference
    metadata_schema: SchemaReference


class EvaluationMetricReference(BaseModel):
    """The business identity of an exact Evaluation Metric Definition revision."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    namespaced_name: str = Field(
        pattern=r"^[a-z][a-z0-9-]*(?:\.[a-z][a-z0-9-]*)+$"
    )
    evaluator_revision: int = Field(ge=1)

    @classmethod
    def from_definition(
        cls, definition: EvaluationMetricDefinition
    ) -> "EvaluationMetricReference":
        return cls(
            namespaced_name=definition.namespaced_name,
            evaluator_revision=definition.evaluator_revision,
        )


class ConfiguredEvaluator(BaseModel):
    """A suite-local evaluator configuration, without runtime provider settings."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(pattern=r"^[a-z][a-z0-9-]*$")
    evaluator_revision: int = Field(ge=1)
    configuration: Mapping[str, Any] = Field(default_factory=dict)
    rubrics: tuple[EvaluationRubricRevisionReference, ...] = ()
    metrics: tuple[EvaluationMetricReference, ...] = ()
    configuration_fingerprint: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )

    def model_post_init(self, __context: Any) -> None:
        if _contains_runtime_execution_setting(self.configuration):
            raise ValueError(
                "suite evaluator configuration cannot select provider or model settings"
            )
        canonical_configuration_json(self.configuration)
        fingerprint = configuration_fingerprint(self.configuration)
        if (
            self.configuration_fingerprint is not None
            and self.configuration_fingerprint != fingerprint
        ):
            raise ValueError("configuration_fingerprint does not match configuration")
        object.__setattr__(self, "configuration_fingerprint", fingerprint)


def _contains_runtime_execution_setting(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(
            str(key).lower().replace("-", "_") in _RUNTIME_EXECUTION_SETTING_KEYS
            or _contains_runtime_execution_setting(item)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple, set, frozenset)):
        return any(_contains_runtime_execution_setting(item) for item in value)
    return False


class EvaluationSuite(BaseModel):
    """A revisioned, executable, provider-neutral evaluation definition."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    identity: EvaluationSuiteIdentity
    description: str = Field(min_length=1)
    task_contract: EvaluationTaskContract
    case_evaluators: tuple[ConfiguredEvaluator, ...] = ()
    report_evaluators: tuple[ConfiguredEvaluator, ...] = Field(min_length=1)
    rubrics: tuple[EvaluationRubricRevisionReference, ...] = ()
    metrics: tuple[EvaluationMetricDefinition, ...] = ()
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def has_unique_suite_local_references(self) -> "EvaluationSuite":
        evaluator_names = [
            evaluator.name
            for evaluator in (*self.case_evaluators, *self.report_evaluators)
        ]
        if len(evaluator_names) != len(set(evaluator_names)):
            raise ValueError("suite-local evaluator names must be unique")
        rubric_identities = [
            (rubric.business_id, rubric.revision) for rubric in self.rubrics
        ]
        if len(rubric_identities) != len(set(rubric_identities)):
            raise ValueError("a suite cannot repeat a rubric revision")
        metric_identities = [metric.identity for metric in self.metrics]
        if len(metric_identities) != len(set(metric_identities)):
            raise ValueError("a suite cannot repeat a metric definition")
        declared_rubrics = set(self.rubrics)
        declared_metrics = {
            EvaluationMetricReference.from_definition(metric) for metric in self.metrics
        }
        for evaluator in (*self.case_evaluators, *self.report_evaluators):
            if any(rubric not in declared_rubrics for rubric in evaluator.rubrics) or any(
                metric not in declared_metrics for metric in evaluator.metrics
            ):
                raise ValueError(
                    "evaluator references an incompatible rubric or metric revision"
                )
        return self

    def model_post_init(self, __context: Any) -> None:
        semantic_content = self.model_dump(mode="json", exclude={"content_hash"})
        semantic_content["identity"].pop("record_id", None)
        fingerprint = content_fingerprint(semantic_content)
        if self.content_hash is not None and self.content_hash != fingerprint:
            raise ValueError("content_hash does not match the evaluation suite")
        object.__setattr__(self, "content_hash", fingerprint)

    def validate_cases(
        self, cases: tuple[EvaluationCase[Any, Any, Any], ...]
    ) -> tuple[EvaluationCase[Any, Any, Any], ...]:
        """Reject authored cases that do not exactly implement the suite task contract."""
        for evaluation_case in cases:
            if not evaluation_case.input_schema.is_exactly_compatible_with(
                self.task_contract.input_schema
            ):
                raise ValueError("case input schema is incompatible with the suite")
            if not evaluation_case.metadata_schema.is_exactly_compatible_with(
                self.task_contract.metadata_schema
            ):
                raise ValueError("case metadata schema is incompatible with the suite")
            if (
                evaluation_case.expected_output_schema is None
                or evaluation_case.expected_output is None
                or not evaluation_case.expected_output_schema.is_exactly_compatible_with(
                    self.task_contract.output_schema
                )
            ):
                raise ValueError("case output schema is incompatible with the suite")
        return cases

    def execute(
        self,
        *,
        cases: tuple[EvaluationCase[Any, Any, Any], ...],
        task: Callable[[Any], Any],
        evaluator_resolver: Callable[[ConfiguredEvaluator], Evaluator | ReportEvaluator],
    ) -> EvaluationReport[Any, Any, Any]:
        """Execute compatible cases through the provider-neutral pydantic-evals seam."""
        selected_cases = self.validate_cases(cases)
        case_evaluators = [
            self._resolve_case_evaluator(configured, evaluator_resolver)
            for configured in self.case_evaluators
        ]
        report_evaluators = [
            self._resolve_report_evaluator(configured, evaluator_resolver)
            for configured in self.report_evaluators
        ]
        dataset = Dataset(
            name=f"{self.identity.business_id}@{self.identity.revision}",
            cases=[
                Case(
                    name=(
                        f"{evaluation_case.identity.business_id}"
                        f"@{evaluation_case.identity.revision}"
                    ),
                    inputs=evaluation_case.task_input,
                    expected_output=evaluation_case.expected_output,
                    metadata=evaluation_case.metadata,
                )
                for evaluation_case in selected_cases
            ],
            evaluators=case_evaluators,
            report_evaluators=report_evaluators,
        )
        return dataset.evaluate_sync(task, progress=False, max_concurrency=1)

    @staticmethod
    def _resolve_case_evaluator(
        configured: ConfiguredEvaluator,
        resolver: Callable[[ConfiguredEvaluator], Evaluator | ReportEvaluator],
    ) -> Evaluator:
        resolved = resolver(configured)
        if not isinstance(resolved, Evaluator):
            raise ValueError(f"{configured.name} did not resolve to a case evaluator")
        return resolved

    @staticmethod
    def _resolve_report_evaluator(
        configured: ConfiguredEvaluator,
        resolver: Callable[[ConfiguredEvaluator], Evaluator | ReportEvaluator],
    ) -> ReportEvaluator:
        resolved = resolver(configured)
        if not isinstance(resolved, ReportEvaluator):
            raise ValueError(f"{configured.name} did not resolve to a report evaluator")
        return resolved
