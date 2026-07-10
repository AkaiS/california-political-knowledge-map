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


class DeclaredArtifactReference(BaseModel):
    """A content-addressed artifact consumed by an authored definition."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    role: str = Field(min_length=1)


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
    artifacts: tuple[DeclaredArtifactReference, ...] = ()

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

    @classmethod
    def from_case(
        cls, evaluation_case: EvaluationCase[Any, Any, Any]
    ) -> "EvaluationCaseRevisionReference":
        return cls(
            record_id=evaluation_case.identity.record_id,
            business_id=evaluation_case.identity.business_id,
            revision=evaluation_case.identity.revision,
            content_hash=evaluation_case.content_hash,
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
