import re
from typing import Any

from pydantic import BaseModel, Field, field_validator


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
    source: str = Field(..., description="Source node name. Do NOT name this key 'source_name', it must be 'source'.")
    target: str = Field(..., description="Target node name. Do NOT name this key 'target_name', it must be 'target'.")
    relationship_type: str = Field(..., description="Relationship type")
    properties: dict[str, Any] = Field(default_factory=dict, description="Relationship metadata")

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
