"""Executable evaluation-suite and metric contracts."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import Evaluator, EvaluatorSpec, ReportEvaluator
from pydantic_evals.reporting import EvaluationReport

from .definitions import (
    EvaluationCase,
    EvaluationGoldSet,
    EvaluationRequirementCatalog,
    EvaluationRubric,
    EvaluationSplit,
    EvaluationTaskContract,
    SchemaReference,
    canonical_configuration_json,
    configuration_fingerprint,
    content_fingerprint,
    new_uuid7,
)
from .reporting import ResolvedSchemaBinding, SchemaRegistry, evaluator_version_tag
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


class _ConfiguredCaseEvaluator(Evaluator):
    """Expose the suite-owned behavioral identity to Pydantic Evals."""

    def __init__(self, configured: ConfiguredEvaluator, delegate: Evaluator) -> None:
        self.configured = configured
        self.delegate = delegate

    def get_default_evaluation_name(self) -> str:
        return self.delegate.get_default_evaluation_name()

    def as_spec(self) -> EvaluatorSpec:
        return self.delegate.as_spec()

    def get_evaluator_version(self) -> str:
        return evaluator_version_tag(
            self.configured.evaluator_revision,
            self.configured.configuration_fingerprint,
        )

    def evaluate(self, ctx: Any) -> Any:
        return self.delegate.evaluate(ctx)

    async def evaluate_async(self, ctx: Any) -> Any:
        return await self.delegate.evaluate_async(ctx)


class ConfiguredEvaluatorReference(BaseModel):
    """A reference to one case Configured Evaluator declared by a Suite."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(pattern=r"^[a-z][a-z0-9-]*$")
    evaluator_revision: int | None = Field(default=None, ge=1)

    @model_validator(mode="before")
    @classmethod
    def accept_evaluator_name_alias(cls, value: Any) -> Any:
        if isinstance(value, Mapping) and "name" not in value:
            value = dict(value)
            if "evaluator_name" in value:
                value["name"] = value.pop("evaluator_name")
        return value

    @property
    def evaluator_name(self) -> str:
        return self.name


class EvaluationRequirementBinding(BaseModel):
    """A Suite-owned, non-empty assignment for one Evaluation Requirement."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    requirement: str = Field(pattern=r"^[a-z][a-z0-9]*(?:[-_.][a-z0-9]+)*$")
    evaluators: tuple[ConfiguredEvaluatorReference, ...] = Field(min_length=1)

    @model_validator(mode="before")
    @classmethod
    def normalize_binding_fields(cls, value: Any) -> Any:
        if not isinstance(value, Mapping):
            return value
        normalized = dict(value)
        if "requirement" not in normalized:
            for alias in ("requirement_key", "key"):
                if alias in normalized:
                    normalized["requirement"] = normalized.pop(alias)
                    break
        if "evaluators" not in normalized:
            for alias in (
                "evaluator_references",
                "configured_evaluator_references",
                "configured_evaluators",
                "evaluator_names",
            ):
                if alias in normalized:
                    raw = normalized.pop(alias)
                    normalized["evaluators"] = tuple(
                        item
                        if isinstance(item, Mapping)
                        else {"name": item}
                        for item in raw
                    )
                    break
        return normalized

    @model_validator(mode="after")
    def has_distinct_evaluator_references(self) -> "EvaluationRequirementBinding":
        names = [reference.name for reference in self.evaluators]
        if len(names) != len(set(names)):
            raise ValueError(
                "an Evaluation Requirement Binding cannot repeat an evaluator"
            )
        return self

    @property
    def evaluator_references(self) -> tuple[ConfiguredEvaluatorReference, ...]:
        return self.evaluators


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
    requirement_catalog: EvaluationRequirementCatalog = Field(
        default_factory=EvaluationRequirementCatalog
    )
    case_evaluators: tuple[ConfiguredEvaluator, ...] = ()
    suite_case_evaluators: tuple[ConfiguredEvaluatorReference, ...] = ()
    requirement_bindings: tuple[EvaluationRequirementBinding, ...] = ()
    report_evaluators: tuple[ConfiguredEvaluator, ...] = Field(min_length=1)
    rubrics: tuple[EvaluationRubricRevisionReference, ...] = ()
    metrics: tuple[EvaluationMetricDefinition, ...] = ()
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="before")
    @classmethod
    def normalize_reference_field_aliases(cls, value: Any) -> Any:
        if not isinstance(value, Mapping):
            return value
        normalized = dict(value)
        if (
            "requirement_catalog" not in normalized
            and "evaluation_requirement_catalog" in normalized
        ):
            normalized["requirement_catalog"] = normalized.pop(
                "evaluation_requirement_catalog"
            )
        if "suite_case_evaluators" not in normalized:
            for alias in (
                "suite_wide_case_evaluators",
                "suite_wide_case_evaluator_references",
                "suite_case_evaluator_references",
                "case_evaluator_references",
            ):
                if alias in normalized:
                    normalized["suite_case_evaluators"] = normalized.pop(alias)
                    break
        if (
            "requirement_bindings" not in normalized
            and "evaluation_requirement_bindings" in normalized
        ):
            normalized["requirement_bindings"] = normalized.pop(
                "evaluation_requirement_bindings"
            )
        return normalized

    @model_validator(mode="after")
    def has_unique_suite_local_references(self) -> "EvaluationSuite":
        evaluator_names = [
            evaluator.name
            for evaluator in (*self.case_evaluators, *self.report_evaluators)
        ]
        if len(evaluator_names) != len(set(evaluator_names)):
            raise ValueError("suite-local evaluator names must be unique")
        declared_case_evaluators = {
            evaluator.name: evaluator for evaluator in self.case_evaluators
        }
        declared_report_evaluators = {
            evaluator.name for evaluator in self.report_evaluators
        }

        suite_references = self._suite_wide_case_evaluator_references()
        self._validate_evaluator_references(
            suite_references,
            declared_case_evaluators=declared_case_evaluators,
            declared_report_evaluators=declared_report_evaluators,
            scope="Suite-wide Case Evaluators",
        )
        if len({reference.name for reference in suite_references}) != len(
            suite_references
        ):
            raise ValueError("Suite-wide Case Evaluator references must be distinct")

        binding_requirements = [
            binding.requirement for binding in self.requirement_bindings
        ]
        if len(binding_requirements) != len(set(binding_requirements)):
            raise ValueError("a Suite cannot repeat an Evaluation Requirement Binding")
        referenced_case_evaluators = {reference.name for reference in suite_references}
        for binding in self.requirement_bindings:
            if not self.requirement_catalog.contains(binding.requirement):
                raise ValueError(
                    "Evaluation Requirement Binding references an unknown requirement: "
                    + binding.requirement
                )
            self._validate_evaluator_references(
                binding.evaluators,
                declared_case_evaluators=declared_case_evaluators,
                declared_report_evaluators=declared_report_evaluators,
                scope=f"binding for {binding.requirement}",
            )
            referenced_case_evaluators.update(
                reference.name for reference in binding.evaluators
            )

        if set(declared_case_evaluators) != referenced_case_evaluators:
            dead = sorted(set(declared_case_evaluators) - referenced_case_evaluators)
            if dead:
                raise ValueError(
                    "every configured case evaluator must be referenced by the Suite: "
                    + ", ".join(dead)
                )
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

    def _suite_wide_case_evaluator_references(
        self,
    ) -> tuple[ConfiguredEvaluatorReference, ...]:
        """Return explicit references, preserving the pre-binding API when unused."""
        if (
            not self.suite_case_evaluators
            and not self.requirement_bindings
            and not self.requirement_catalog.requirements
        ):
            return tuple(
                ConfiguredEvaluatorReference(name=evaluator.name)
                for evaluator in self.case_evaluators
            )
        return self.suite_case_evaluators

    @staticmethod
    def _validate_evaluator_references(
        references: tuple[ConfiguredEvaluatorReference, ...],
        *,
        declared_case_evaluators: dict[str, ConfiguredEvaluator],
        declared_report_evaluators: set[str],
        scope: str,
    ) -> None:
        for reference in references:
            if reference.name in declared_report_evaluators:
                raise ValueError(
                    f"{scope} may reference only declared case evaluators: "
                    f"{reference.name} is a report evaluator"
                )
            configured = declared_case_evaluators.get(reference.name)
            if configured is None:
                raise ValueError(
                    f"{scope} references an undeclared case evaluator: {reference.name}"
                )
            if (
                reference.evaluator_revision is not None
                and reference.evaluator_revision != configured.evaluator_revision
            ):
                raise ValueError(
                    f"{scope} references {reference.name} at an incompatible evaluator revision"
                )

    @property
    def suite_wide_case_evaluator_references(
        self,
    ) -> tuple[ConfiguredEvaluatorReference, ...]:
        return self._suite_wide_case_evaluator_references()

    def resolve_case_evaluators(
        self, evaluation_case: EvaluationCase[Any, Any, Any]
    ) -> tuple[ConfiguredEvaluator, ...]:
        """Resolve the additive, deduplicated case evaluator assignment for a case."""
        self.validate_cases((evaluation_case,))
        references = list(self._suite_wide_case_evaluator_references())
        bindings = {binding.requirement: binding for binding in self.requirement_bindings}
        for requirement in evaluation_case.requirements:
            binding = bindings.get(requirement)
            if binding is None:
                raise ValueError(
                    f"Evaluation Requirement has no Suite binding: {requirement}"
                )
            references.extend(binding.evaluators)

        unique_names = dict.fromkeys(reference.name for reference in references)
        configured_by_name = {
            evaluator.name: evaluator for evaluator in self.case_evaluators
        }
        return tuple(configured_by_name[name] for name in unique_names)

    def resolve_metric_definition(
        self, reference: EvaluationMetricReference
    ) -> EvaluationMetricDefinition:
        """Resolve one observation identity to its singular authored definition."""
        for metric in self.metrics:
            if metric.identity == (
                reference.namespaced_name,
                reference.evaluator_revision,
            ):
                return metric
        raise ValueError(
            "Evaluation Suite does not declare metric "
            f"{reference.namespaced_name}@{reference.evaluator_revision}"
        )

    def resolve_structured_metric_binding(
        self,
        reference: EvaluationMetricReference,
        schemas: SchemaRegistry,
    ) -> ResolvedSchemaBinding:
        """Resolve a structured metric identity and its registered runtime schema."""
        metric = self.resolve_metric_definition(reference)
        if metric.value_type is not EvaluationMetricValueType.STRUCTURED:
            raise ValueError(
                f"metric {reference.namespaced_name} is not structured"
            )
        assert metric.structured_schema is not None
        return schemas.resolve_binding(metric.structured_schema)

    def preflight_selected_cases(
        self,
        *,
        gold_set: EvaluationGoldSet,
        cases: tuple[EvaluationCase[Any, Any, Any], ...],
        selection: Callable[[EvaluationCase[Any, Any, Any]], bool]
        | Iterable[str]
        | None = None,
        split: EvaluationSplit | None = None,
    ) -> "EvaluationPreflightResult":
        """Resolve selected Gold Set cases before an Evaluation Run is created."""
        from .preflight import preflight_selected_cases

        return preflight_selected_cases(
            suite=self,
            gold_set=gold_set,
            cases=cases,
            selection=selection,
            split=split,
        )

    def preflight(self, **kwargs: Any) -> "EvaluationPreflightResult":
        """Convenience alias for the Suite-owned preflight boundary."""
        return self.preflight_selected_cases(**kwargs)

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
            evaluation_case.validate_requirements(self.requirement_catalog)
        return cases

    def execute(
        self,
        *,
        cases: tuple[EvaluationCase[Any, Any, Any], ...],
        task: Callable[[Any], Any],
        evaluator_resolver: Callable[[ConfiguredEvaluator], Evaluator | ReportEvaluator],
        plan: "ResolvedEvaluationPlan | None" = None,
        checkpoint_sink: "EvaluationCheckpointSink | None" = None,
        max_concurrency: int = 1,
    ) -> EvaluationReport[Any, Any, Any]:
        """Execute compatible cases through the provider-neutral pydantic-evals seam."""
        if plan is not None:
            from .engine import EvaluationEngine

            return EvaluationEngine(checkpoint_sink).execute(
                plan=plan,
                suite=self,
                cases=cases,
                task=task,
                evaluator_resolver=evaluator_resolver,
                max_concurrency=max_concurrency,
            )

        selected_cases = self.validate_cases(cases)
        suite_wide_references = self._suite_wide_case_evaluator_references()
        configured_by_name = {evaluator.name: evaluator for evaluator in self.case_evaluators}
        suite_wide_configured = tuple(
            configured_by_name[reference.name] for reference in suite_wide_references
        )
        case_evaluators = [
            self._resolve_case_evaluator(configured, evaluator_resolver)
            for configured in suite_wide_configured
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
                    evaluators=tuple(
                        self._resolve_case_evaluator(configured, evaluator_resolver)
                        for configured in self.resolve_case_evaluators(evaluation_case)
                        if configured.name
                        not in {reference.name for reference in suite_wide_references}
                    ),
                )
                for evaluation_case in selected_cases
            ],
            evaluators=case_evaluators,
            report_evaluators=report_evaluators,
        )
        return dataset.evaluate_sync(
            task, progress=False, max_concurrency=max_concurrency
        )

    @staticmethod
    def _resolve_case_evaluator(
        configured: ConfiguredEvaluator,
        resolver: Callable[[ConfiguredEvaluator], Evaluator | ReportEvaluator],
    ) -> Evaluator:
        resolved = resolver(configured)
        if not isinstance(resolved, Evaluator):
            raise ValueError(f"{configured.name} did not resolve to a case evaluator")
        return _ConfiguredCaseEvaluator(configured, resolved)

    @staticmethod
    def _resolve_report_evaluator(
        configured: ConfiguredEvaluator,
        resolver: Callable[[ConfiguredEvaluator], Evaluator | ReportEvaluator],
    ) -> ReportEvaluator:
        resolved = resolver(configured)
        if not isinstance(resolved, ReportEvaluator):
            raise ValueError(f"{configured.name} did not resolve to a report evaluator")
        return resolved
