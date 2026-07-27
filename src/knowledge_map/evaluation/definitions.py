"""Version-controlled evaluation definition contracts.

The models in this module deliberately describe authored data only.  Runtime
provider settings and evaluator configuration belong to later evaluation-suite
and run-configuration contracts.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import time
from enum import Enum
from collections.abc import Mapping
from typing import Any, Generic, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretBytes, SecretStr, model_validator


InputT = TypeVar("InputT", bound=BaseModel)
OutputT = TypeVar("OutputT", bound=BaseModel)
MetadataT = TypeVar("MetadataT", bound=BaseModel)


def new_uuid7() -> UUID:
    """Return an application-generated RFC 9562 UUIDv7."""
    timestamp_ms = int(time.time_ns() // 1_000_000) & ((1 << 48) - 1)
    random_bits = secrets.randbits(74)
    value = timestamp_ms << 80
    value |= 0x7 << 76
    value |= ((random_bits >> 62) & 0xFFF) << 64
    value |= 0b10 << 62
    value |= random_bits & ((1 << 62) - 1)
    return UUID(int=value)


def canonical_json(value: Any) -> str:
    """Serialize JSON-compatible data into stable bytes for fingerprinting."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def content_fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


_CREDENTIAL_KEY_FRAGMENTS = (
    "api_key",
    "apikey",
    "credential",
    "password",
    "secret",
    "token",
    "authorization",
)
_OMIT = object()


def canonical_configuration_json(configuration: Any) -> str:
    """Return stable, secret-free serialized execution configuration."""
    sanitized = _without_credentials(configuration)
    if sanitized is _OMIT:
        raise ValueError("configuration cannot be a credential value")
    return canonical_json(sanitized)


def configuration_fingerprint(configuration: Any) -> str:
    """Fingerprint only the material, non-secret execution configuration."""
    return hashlib.sha256(
        canonical_configuration_json(configuration).encode("utf-8")
    ).hexdigest()


def _without_credentials(value: Any) -> Any:
    if isinstance(value, (SecretStr, SecretBytes)):
        return _OMIT
    if isinstance(value, BaseModel):
        return _without_credentials(value.model_dump())
    if isinstance(value, Mapping):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            key = str(key)
            if _is_credential_key(key):
                continue
            cleaned_item = _without_credentials(item)
            if cleaned_item is not _OMIT:
                sanitized[key] = cleaned_item
        return sanitized
    if isinstance(value, (list, tuple, set, frozenset)):
        return [
            cleaned_item
            for item in value
            if (cleaned_item := _without_credentials(item)) is not _OMIT
        ]
    if isinstance(value, UUID):
        return str(value)
    return value


def _is_credential_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return any(fragment in normalized for fragment in _CREDENTIAL_KEY_FRAGMENTS)


class EvaluationCaseIdentity(BaseModel):
    """The opaque and business identifiers for one immutable case revision."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    record_id: UUID = Field(default_factory=new_uuid7)
    business_id: str = Field(min_length=1)
    revision: int = Field(ge=1)


class EvaluationGoldSetIdentity(EvaluationCaseIdentity):
    """The opaque and business identifiers for one immutable Gold Set version."""


class EvaluationRubricIdentity(EvaluationCaseIdentity):
    """The opaque and business identifiers for one immutable rubric revision."""


class SchemaReference(BaseModel):
    """An exact, revisioned Pydantic schema contract."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    identity: str = Field(min_length=1)
    revision: int = Field(ge=1)
    model_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def for_model(
        cls,
        model_type: type[BaseModel],
        *,
        identity: str,
        revision: int,
    ) -> "SchemaReference":
        return cls(
            identity=identity,
            revision=revision,
            model_fingerprint=content_fingerprint(model_type.model_json_schema()),
        )

    def is_exactly_compatible_with(self, other: "SchemaReference") -> bool:
        return self == other


class EvaluationTaskContract(BaseModel):
    """The exact typed inputs, outputs, and metadata of one component operation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    input_schema: SchemaReference
    output_schema: SchemaReference
    metadata_schema: SchemaReference

    def is_exactly_compatible_with(self, other: "EvaluationTaskContract") -> bool:
        return (
            self.input_schema.is_exactly_compatible_with(other.input_schema)
            and self.output_schema.is_exactly_compatible_with(other.output_schema)
            and self.metadata_schema.is_exactly_compatible_with(other.metadata_schema)
        )



class DeclaredArtifactReference(BaseModel):
    """A content-addressed artifact consumed by an authored definition."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    role: str = Field(min_length=1)


class EvaluationRequirement(BaseModel):
    """One stable semantic key in a component's closed requirement catalog."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str = Field(pattern=r"^[a-z][a-z0-9]*(?:[-_.][a-z0-9]+)*$")
    semantic_description: str = Field(min_length=1)

    @model_validator(mode="before")
    @classmethod
    def accept_description_alias(cls, value: Any) -> Any:
        if isinstance(value, Mapping) and "semantic_description" not in value:
            value = dict(value)
            if "description" in value:
                value["semantic_description"] = value.pop("description")
        return value


class EvaluationRequirementCatalog(BaseModel):
    """The closed vocabulary of Evaluation Requirement keys for a component."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    requirements: tuple[EvaluationRequirement, ...] = ()

    @model_validator(mode="before")
    @classmethod
    def normalize_requirement_entries(cls, value: Any) -> Any:
        if not isinstance(value, Mapping):
            return value
        normalized = dict(value)
        if "requirements" not in normalized:
            for alias in ("entries", "keys"):
                if alias in normalized:
                    normalized["requirements"] = normalized.pop(alias)
                    break
        entries = normalized.get("requirements", ())
        if isinstance(entries, Mapping):
            normalized["requirements"] = tuple(
                {"key": key, "semantic_description": description}
                for key, description in entries.items()
            )
        return normalized

    @model_validator(mode="after")
    def has_unique_keys(self) -> "EvaluationRequirementCatalog":
        keys = [requirement.key for requirement in self.requirements]
        if len(keys) != len(set(keys)):
            raise ValueError("requirement catalog cannot contain duplicate keys")
        if any(
            not requirement.semantic_description.strip()
            for requirement in self.requirements
        ):
            raise ValueError("requirement descriptions must be non-empty")
        return self

    def contains(self, key: str) -> bool:
        return any(requirement.key == key for requirement in self.requirements)

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(requirement.key for requirement in self.requirements)

    @property
    def entries(self) -> tuple[EvaluationRequirement, ...]:
        return self.requirements

    def validate_requirements(self, requirements: tuple[str, ...]) -> tuple[str, ...]:
        unknown = [
            requirement for requirement in requirements if not self.contains(requirement)
        ]
        if unknown:
            raise ValueError(
                "unknown Evaluation Requirement keys: " + ", ".join(unknown)
            )
        return requirements

    def validate_case(
        self, evaluation_case: "EvaluationCase[Any, Any, Any]"
    ) -> "EvaluationCase[Any, Any, Any]":
        self.validate_requirements(evaluation_case.requirements)
        return evaluation_case

    def description_for(self, key: str) -> str:
        for requirement in self.requirements:
            if requirement.key == key:
                return requirement.semantic_description
        raise ValueError(f"unknown Evaluation Requirement key: {key}")


# The catalog entry is a definition rather than a separately revisioned artifact.
EvaluationRequirementDefinition = EvaluationRequirement


class AuthoredDefinitionConflictError(ValueError):
    """A business identity and revision were reused for different content."""


class _AuthoredDefinition(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    def _semantic_content(self) -> dict[str, Any]:
        data = self.model_dump(mode="json", exclude={"content_hash"})
        data["identity"].pop("record_id", None)
        return data

    def model_post_init(self, __context: Any) -> None:
        computed_hash = content_fingerprint(self._semantic_content())
        if self.content_hash is not None and self.content_hash != computed_hash:
            raise ValueError("content_hash does not match the authored definition")
        object.__setattr__(self, "content_hash", computed_hash)


class EvaluationCase(_AuthoredDefinition, Generic[InputT, OutputT, MetadataT]):
    """One immutable, typed authored example for a component task."""

    identity: EvaluationCaseIdentity
    input_schema: SchemaReference
    expected_output_schema: SchemaReference | None = None
    metadata_schema: SchemaReference
    task_input: InputT
    expected_output: OutputT | None = None
    metadata: MetadataT
    description: str = Field(min_length=1)
    tags: tuple[str, ...] = ()
    requirements: tuple[str, ...] = ()
    artifacts: tuple[DeclaredArtifactReference, ...] = ()

    @model_validator(mode="before")
    @classmethod
    def accept_requirement_field_alias(cls, value: Any) -> Any:
        if isinstance(value, Mapping) and "requirements" not in value:
            value = dict(value)
            if "evaluation_requirements" in value:
                value["requirements"] = value.pop("evaluation_requirements")
        return value

    @model_validator(mode="after")
    def schemas_match_the_typed_values(self) -> "EvaluationCase[InputT, OutputT, MetadataT]":
        _require_schema_for_value("input_schema", self.input_schema, self.task_input)
        _require_schema_for_value("metadata_schema", self.metadata_schema, self.metadata)

        if self.expected_output is None:
            if self.expected_output_schema is not None:
                raise ValueError(
                    "expected_output_schema requires an expected_output value"
                )
        elif self.expected_output_schema is None:
            raise ValueError("expected_output requires an expected_output_schema")
        else:
            _require_schema_for_value(
                "expected_output_schema",
                self.expected_output_schema,
                self.expected_output,
            )
        return self

    @model_validator(mode="after")
    def has_distinct_requirements(self) -> "EvaluationCase[InputT, OutputT, MetadataT]":
        if len(self.requirements) != len(set(self.requirements)):
            raise ValueError("an Evaluation Case cannot repeat a requirement key")
        if any(not requirement for requirement in self.requirements):
            raise ValueError("Evaluation Requirement keys must be non-empty")
        return self

    def validate_requirements(
        self, catalog: EvaluationRequirementCatalog
    ) -> "EvaluationCase[InputT, OutputT, MetadataT]":
        catalog.validate_requirements(self.requirements)
        return self


class EvaluationSplit(str, Enum):
    TRAINING = "training"
    CALIBRATION = "calibration"
    HELD_OUT = "held-out"


class EvaluationCaseRevisionReference(BaseModel):
    """A content-addressed reference to the exact case revision in a Gold Set."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    record_id: UUID
    business_id: str = Field(min_length=1)
    revision: int = Field(ge=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_schema: SchemaReference
    output_schema: SchemaReference
    metadata_schema: SchemaReference

    @classmethod
    def from_case(
        cls, evaluation_case: EvaluationCase[Any, Any, Any]
    ) -> "EvaluationCaseRevisionReference":
        return cls(
            record_id=evaluation_case.identity.record_id,
            business_id=evaluation_case.identity.business_id,
            revision=evaluation_case.identity.revision,
            content_hash=evaluation_case.content_hash,
            input_schema=evaluation_case.input_schema,
            output_schema=evaluation_case.expected_output_schema,
            metadata_schema=evaluation_case.metadata_schema,
        )


class EvaluationGoldSetMembership(BaseModel):
    """A Gold Set's split assignment for one exact Evaluation Case revision."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    case: EvaluationCaseRevisionReference
    split: EvaluationSplit


class EvaluationGoldSet(_AuthoredDefinition):
    """A versioned population of exact Evaluation Case revisions."""

    identity: EvaluationGoldSetIdentity
    description: str = Field(min_length=1)
    task_contract: EvaluationTaskContract
    tags: tuple[str, ...] = ()
    artifacts: tuple[DeclaredArtifactReference, ...] = ()
    memberships: tuple[EvaluationGoldSetMembership, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def does_not_repeat_a_case_revision(self) -> "EvaluationGoldSet":
        revisions = [
            (membership.case.business_id, membership.case.revision)
            for membership in self.memberships
        ]
        if len(revisions) != len(set(revisions)):
            raise ValueError("a Gold Set cannot contain a case revision more than once")
        return self

    @model_validator(mode="after")
    def members_match_task_contract(self) -> "EvaluationGoldSet":
        from .compatibility import evaluate_compatibility

        issues = evaluate_compatibility(None, self)
        if issues:
            issue = issues[0]
            assert issue.schema_role is not None
            field_name = (
                "output" if issue.schema_role == "expected_output" else issue.schema_role
            )
            raise ValueError(
                f"Gold Set member {issue.case_business_id}@{issue.case_revision} "
                f"has an incompatible {field_name} schema"
            )
        return self

    def validate_cases(
        self, cases: tuple[EvaluationCase[Any, Any, Any], ...]
    ) -> tuple[EvaluationCase[Any, Any, Any], ...]:
        """Revalidate supplied case values against this Gold Set's contract."""
        from .compatibility import evaluate_compatibility

        issues = evaluate_compatibility(None, self, cases)
        case_issues = [issue for issue in issues if issue.source == "case"]
        if case_issues:
            issue = case_issues[0]
            assert issue.schema_role is not None
            field_name = (
                "output" if issue.schema_role == "expected_output" else issue.schema_role
            )
            raise ValueError(
                f"case {issue.case_business_id}@{issue.case_revision} "
                f"has an incompatible {field_name} schema for the Gold Set"
            )
        return cases


class EvaluationRubric(_AuthoredDefinition):
    """A versioned, human-authored policy for a model-based evaluator."""

    identity: EvaluationRubricIdentity
    description: str = Field(min_length=1)
    criteria: tuple[str, ...] = Field(min_length=1)
    assertions: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    artifacts: tuple[DeclaredArtifactReference, ...] = ()


def _require_schema_for_value(
    field_name: str, schema: SchemaReference, value: BaseModel
) -> None:
    actual_fingerprint = content_fingerprint(type(value).model_json_schema())
    if schema.model_fingerprint != actual_fingerprint:
        raise ValueError(
            f"{field_name} does not identify the exact Pydantic schema for its value"
        )


def assert_same_revision_content(
    existing: _AuthoredDefinition, candidate: _AuthoredDefinition
) -> None:
    """Reject an import that reuses an authored revision for different content."""
    if type(existing) is not type(candidate):
        raise AuthoredDefinitionConflictError("authored definition kinds differ")
    if existing.identity.business_id != candidate.identity.business_id:
        raise AuthoredDefinitionConflictError("authored business identities differ")
    if existing.identity.revision != candidate.identity.revision:
        raise AuthoredDefinitionConflictError("authored revisions differ")
    if existing.content_hash != candidate.content_hash:
        raise AuthoredDefinitionConflictError(
            "authored content changed without a new revision"
        )
