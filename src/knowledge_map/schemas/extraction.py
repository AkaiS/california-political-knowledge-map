import re
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel, field_validator

from knowledge_map.prompts import load_prompt


class Node(BaseModel):
    name: str = Field(..., description="Canonical name of the entity")
    label: str = Field(..., description="Entity label")
    sub_labels: list[str] = Field(default_factory=list, description="Ontology sub-labels")
    properties: dict[str, Any] = Field(default_factory=dict, description="Metadata properties")

    @field_validator("name", "label", mode="before")
    @classmethod
    def clean_strings(cls, v: Any) -> str:
        if not isinstance(v, str):
            raise ValueError("Must be a string")
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Must be a non-empty string")
        return cleaned

    @field_validator("label")
    @classmethod
    def validate_label(cls, v: str) -> str:
        if not re.match(r"^[A-Za-z0-9_]+$", v):
            raise ValueError(f"Invalid character in node label: {v}")
        return v

class Relationship(BaseModel):
    """A claim between two named entities.

    An endpoint is a name plus, optionally, the label of the node it refers to,
    which disambiguates two entities sharing a canonical name.  The endpoint
    labels persistence reads back are always the ones conformance stamped; a
    model's claimed label is consulted only where the ontology leaves a genuine
    choice.
    """

    source: str = Field(..., description=load_prompt("extraction/source-key-guidance", version=1))
    target: str = Field(..., description=load_prompt("extraction/target-key-guidance", version=1))
    relationship_type: str = Field(..., description="Relationship type")
    properties: dict[str, Any] = Field(default_factory=dict, description="Relationship metadata")
    source_label: str | None = Field(
        default=None, description=load_prompt("extraction/source-label-guidance", version=1)
    )
    target_label: str | None = Field(
        default=None, description=load_prompt("extraction/target-label-guidance", version=1)
    )

    @field_validator("source", "target", mode="before")
    @classmethod
    def clean_node_references(cls, v: Any) -> str:
        if not isinstance(v, str):
            raise ValueError("Must be a string")
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Must be a non-empty string")
        return cleaned

    @field_validator("relationship_type", mode="before")
    @classmethod
    def clean_and_normalize_relationship_type(cls, v: Any) -> str:
        if not isinstance(v, str):
            raise ValueError("Must be a string")
        cleaned = v.strip().upper()
        if not cleaned:
            raise ValueError("Must be a non-empty string")
        return cleaned

    @field_validator("relationship_type")
    @classmethod
    def validate_relationship_type(cls, v: str) -> str:
        if not re.match(r"^[A-Za-z0-9_]+$", v):
            raise ValueError(f"Invalid character in relationship type: {v}")
        return v

class StanceAlignmentVerdict(BaseModel):
    """The Stance Alignment Critic's decision for one `DECLARED_STANCE` claim.

    Carries the claim's two endpoint names so a verdict can be matched back to
    the claim it was asked about, and nothing else: the critic supplies the one
    property the ontology says a stance entails, and is not permitted to
    restate, move, or invent the claim itself.

    ``NO_STANCE_STATED`` is the abstention, and is not an alignment: a passage
    can name both endpoints without saying what the source thinks of the
    target, and a critic offered only the three directions answers such a
    passage by inventing one.  It is deliberately outside the ontology's
    vocabulary so the write path cannot store it.
    """

    model_config = ConfigDict(extra="forbid")

    source: str = Field(..., description=load_prompt("stance-alignment/source-guidance", version=1))
    target: str = Field(..., description=load_prompt("stance-alignment/target-guidance", version=1))
    alignment: Literal["POSITIVE", "NEGATIVE", "NEUTRAL", "NO_STANCE_STATED"] = Field(
        ...,
        description=(
            load_prompt("stance-alignment/verdict-guidance", version=1)
        ),
    )

    @field_validator("source", "target", mode="before")
    @classmethod
    def clean_endpoint_names(cls, v: Any) -> str:
        if not isinstance(v, str):
            raise ValueError("Must be a string")
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Must be a non-empty string")
        return cleaned


class ExtractionResult(BaseModel):
    nodes: list[Node] = Field(default_factory=list, description="Extracted entities")
    relationships: list[Relationship] = Field(default_factory=list, description="Extracted relationships")


class DropCategory(StrEnum):
    """The closed set of buckets an Adherence Report drop can fall into.

    Record against a member, never a string: a mistyped category must fail at
    the drop site rather than open a bucket nobody reads.
    """

    REJECTED_LABELS = "rejected_labels"
    REJECTED_RELATIONSHIP_TYPES = "rejected_relationship_types"
    REJECTED_PROPERTY_NAMES = "rejected_property_names"
    REJECTED_RELATIONSHIP_PROPERTY_NAMES = "rejected_relationship_property_names"


class DroppedItem(BaseModel):
    """How often one ontology item was dropped, and where it was first seen."""

    count: int = 0
    example_chunk_id: str


class AdherenceReport(RootModel[dict[DropCategory, dict[str, DroppedItem]]]):
    """Ontology items an extraction adapter dropped from model output.

    Shaped ``category -> dropped value -> {"count", "example_chunk_id"}``.
    Every category is present from the start, so a reader indexes any of them
    without checking.
    """

    root: dict[DropCategory, dict[str, DroppedItem]] = Field(
        default_factory=lambda: {category: {} for category in DropCategory}
    )

    def __getitem__(self, category: DropCategory | str) -> dict[str, DroppedItem]:
        return self.root[DropCategory(category)]

    def record(self, category: DropCategory, value: str, chunk_id: str) -> None:
        """Count one more drop of ``value`` under ``category``."""
        entries = self.root[DropCategory(category)]
        entry = entries.get(value)
        if entry is None:
            entries[value] = DroppedItem(count=1, example_chunk_id=chunk_id)
        else:
            entry.count += 1

    def as_json_dict(self) -> dict[str, dict[str, dict[str, str | int]]]:
        """The report as plain JSON-serialisable data."""
        return self.model_dump(mode="json")
