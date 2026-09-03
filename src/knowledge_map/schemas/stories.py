from typing import Any, List, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator
from .pipeline import ContentLink, IngestionArticle, StoryStatus


class Story(BaseModel):
    """The extracted content held for a validated article, as persisted in the stories table."""
    model_config = ConfigDict(extra="forbid")

    url: str = Field(..., description="The URL of the article the content was extracted from")
    title: str = Field(..., description="The headline of the article")
    category: Optional[str] = Field(None, description="The publication's own category for the article")
    author: Optional[str] = Field(None, description="The normalized author string, comma-separated for multiple authors")
    published_date: Optional[str] = Field(None, description="The publication date, UTC-formatted when it could be parsed")
    summary: Optional[str] = Field(None, description="The publication's own summary or standfirst")
    content: Optional[str] = Field(None, description="The extracted body text of the article")
    status: StoryStatus = Field(
        StoryStatus.UNPROCESSED, description="How far this Story has progressed through ingestion"
    )
    links: List[ContentLink] = Field(default_factory=list, description="The hyperlinks found in the body")

    @field_validator("url", "title", mode="before")
    @classmethod
    def clean_strings(cls, v: Any) -> str:
        if not isinstance(v, str):
            raise ValueError("Must be a string")
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Must be a non-empty string")
        return cleaned

    def to_ingestion_article(
        self, links: List[ContentLink] | None = None
    ) -> IngestionArticle:
        """Build the ingestion input for this Story and its links."""
        return IngestionArticle(
            url=self.url,
            title=self.title,
            author=self.author,
            published_date=self.published_date,
            content=self.content or "",
            links=list(links) if links is not None else list(self.links),
        )
