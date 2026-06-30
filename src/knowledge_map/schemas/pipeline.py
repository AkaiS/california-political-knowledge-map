from typing import Optional, List
from enum import Enum
from pydantic import BaseModel, Field
from .chunking import ArticleChunk
from .extraction import ExtractionResult

class ArticleStatus(str, Enum):
    UNPROCESSED = "UNPROCESSED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED_DLQ = "FAILED_DLQ"
    SYSTEM_ERROR = "SYSTEM_ERROR"


class SourceArticle(BaseModel):
    url: str = Field(..., description="The URL of the source article")
    title: Optional[str] = Field(None, description="The title of the article")
    author: Optional[str] = Field(None, description="The author(s) of the article")
    published_date: Optional[str] = Field(None, description="The published date of the article")
    content: str = Field(..., description="The full raw text content of the article")

class PipelineResult(BaseModel):
    resolved_text: str = Field(..., description="The coreference-resolved text of the article")
    chunks: List[ArticleChunk] = Field(..., description="The list of chunks generated from the resolved text")
    embeddings: List[List[float]] = Field(..., description="The vector embeddings corresponding to each chunk")
    extractions: List[ExtractionResult] = Field(..., description="The list of extracted entities and relationships per chunk")
