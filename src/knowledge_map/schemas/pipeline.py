from typing import Optional, List
from enum import StrEnum
from pydantic import BaseModel, ConfigDict, Field, field_validator
from .chunking import ArticleChunk
from .extraction import ExtractionResult

class ArticleStatus(StrEnum):
    UNPROCESSED = "UNPROCESSED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED_DLQ = "FAILED_DLQ"
    SYSTEM_ERROR = "SYSTEM_ERROR"


class StoryLink(BaseModel):
    """A hyperlink extracted from an article body."""
    model_config = ConfigDict(extra="forbid")

    url: str
    text: Optional[str] = None

    @field_validator("url", mode="before")
    @classmethod
    def clean_url(cls, value: object) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Must be a non-empty string")
        return value.strip()


class SourceArticle(BaseModel):
    url: str = Field(..., description="The URL of the source article")
    title: Optional[str] = Field(None, description="The title of the article")
    author: Optional[str] = Field(None, description="The author(s) of the article")
    published_date: Optional[str] = Field(None, description="The published date of the article")
    content: str = Field(..., description="The full raw text content of the article")
    links: List[StoryLink] = Field(default_factory=list, description="The hyperlinks found in the article body")

class PipelineResult(BaseModel):
    resolved_text: str = Field(..., description="The coreference-resolved text of the article")
    chunks: List[ArticleChunk] = Field(..., description="The list of chunks generated from the resolved text")
    embeddings: List[List[float]] = Field(..., description="The vector embeddings corresponding to each chunk")
    extractions: List[ExtractionResult] = Field(..., description="The list of extracted entities and relationships per chunk")
    policy_areas: List[str] = Field(default_factory=list, description="The Policy Areas the article discusses, decided once for the article")
