from typing import Dict, Any, List
from pydantic import BaseModel, Field, field_validator, model_validator

class Node(BaseModel):
    name: str = Field(..., description="Canonical name of the entity")
    label: str = Field(..., description="Entity label")
    properties: Dict[str, Any] = Field(default_factory=dict, description="Metadata properties")

    @field_validator("name", "label", mode="before")
    @classmethod
    def clean_strings(cls, v: Any) -> str:
        if not isinstance(v, str):
            raise ValueError("Must be a string")
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Must be a non-empty string")
        return cleaned

class Relationship(BaseModel):
    source: str = Field(..., description="Source node name. Do NOT name this key 'source_name', it must be 'source'.")
    target: str = Field(..., description="Target node name. Do NOT name this key 'target_name', it must be 'target'.")
    relationship_type: str = Field(..., description="Relationship type")
    properties: Dict[str, Any] = Field(default_factory=dict, description="Relationship metadata")

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

class ExtractionResult(BaseModel):
    nodes: List[Node] = Field(default_factory=list, description="Extracted entities")
    relationships: List[Relationship] = Field(default_factory=list, description="Extracted relationships")

    @model_validator(mode="after")
    def validate_relationships(self) -> 'ExtractionResult':
        node_names = {node.name for node in self.nodes}
        for rel in self.relationships:
            if rel.source not in node_names:
                raise ValueError(f"Relationship source '{rel.source}' not found in defined nodes.")
            if rel.target not in node_names:
                raise ValueError(f"Relationship target '{rel.target}' not found in defined nodes.")
        return self
