from typing import Dict, Any, List
from pydantic import BaseModel, Field, field_validator

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
    source: str = Field(..., description="Source node name")
    target: str = Field(..., description="Target node name")
    type: str = Field(..., description="Relationship type")
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

    @field_validator("type", mode="before")
    @classmethod
    def clean_and_normalize_type(cls, v: Any) -> str:
        if not isinstance(v, str):
            raise ValueError("Must be a string")
        cleaned = v.strip().upper()
        if not cleaned:
            raise ValueError("Must be a non-empty string")
        return cleaned

from pydantic import model_validator

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

import os
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from dotenv import load_dotenv

PROMPT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "extraction_prompt.txt")

def load_instructions() -> str:
    if os.path.exists(PROMPT_PATH):
        with open(PROMPT_PATH, "r", encoding="utf-8") as f:
            return f.read()
    else:
        return "Extract entities and relationships from California politics stories."

def get_extraction_agent(defer_check: bool = True) -> Agent:
    load_dotenv()
    ollama_base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    ollama_model = os.environ.get("OLLAMA_MODEL", "gemma4:31b")
    
    provider = OpenAIProvider(
        base_url=f"{ollama_base_url}/v1",
        api_key="ollama",
    )
    
    model = OpenAIChatModel(
        model_name=ollama_model,
        provider=provider,
    )
    
    instructions = load_instructions()
    
    return Agent(
        model,
        output_type=ExtractionResult,
        instructions=instructions,
        defer_model_check=defer_check,
    )

def extract_entities(text: str, agent: Agent | None = None) -> ExtractionResult:
    if agent is None:
        agent = get_extraction_agent()
    result = agent.run_sync(text)
    return result.output



