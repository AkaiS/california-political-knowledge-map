import re
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, RootModel, field_validator


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

    An endpoint is a name plus the label of the node that name refers to. The label
    is what a bare name cannot supply: two entities in one chunk can share a
    canonical name, and the name alone then picks between them arbitrarily. It is a
    sibling field rather than a nested endpoint object because it has to stay
    optional — a relationship built by hand, or read back from an extraction stored
    before labels were asked for, names its endpoints and nothing more.

    Conformance decides what these mean. It resolves each endpoint against the nodes
    beside it and the ontology's shape for the relationship type, and stamps the
    label it settled on; a model's label is consulted only where the ontology leaves
    a genuine choice. What persistence reads back is therefore always the resolved
    label, never the extractor's unexamined claim.

    The label earns a field because it varies per claim: the name alone cannot supply
    it. What a relationship type fixes for every one of its claims — whether it
    flattens a Shortcut Rule's path, for one — needs no field here and no copy on the
    edge, because the type is already carried and the ontology already holds the rule.
    """

    source: str = Field(..., description="Source node name. Do NOT name this key 'source_name', it must be 'source'.")
    target: str = Field(..., description="Target node name. Do NOT name this key 'target_name', it must be 'target'.")
    relationship_type: str = Field(..., description="Relationship type")
    properties: dict[str, Any] = Field(default_factory=dict, description="Relationship metadata")
    source_label: str | None = Field(
        default=None, description="Label of the source node, exactly as that node declares it."
    )
    target_label: str | None = Field(
        default=None, description="Label of the target node, exactly as that node declares it."
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

class ExtractionResult(BaseModel):
    nodes: list[Node] = Field(default_factory=list, description="Extracted entities")
    relationships: list[Relationship] = Field(default_factory=list, description="Extracted relationships")


class DropCategory(StrEnum):
    """The closed set of buckets an Adherence Report drop can fall into.

    A category is not a free-form string: a mistyped one has to fail loudly at
    the drop site rather than quietly open a fifth bucket that no reader of the
    report ever looks in.
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

    Shaped ``category -> dropped value -> {"count", "example_chunk_id"}``, with
    every category present from the start so a reader never has to distinguish
    "nothing was dropped" from "that bucket does not exist".
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
