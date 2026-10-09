"""Reader-facing citations, directions, and verified navigation without chunk bodies."""

from datetime import datetime
from typing import Literal

from pydantic import HttpUrl

from knowledge_map.schemas.query_preparation import QuestionAssessment
from knowledge_map.schemas.retrieval import (
    ArticleGroup,
    NonemptyText,
    RetrievalValue,
    SourceArticleCitation,
)


class GuideArticle(RetrievalValue):
    citation: SourceArticleCitation
    reading_direction: NonemptyText
    section_links: tuple[HttpUrl, ...] = ()


GuideOutcome = Literal[
    "completed",
    "empty",
    "declined",
    "needs_edit",
    "assessment_failed",
    "retrieval_failed",
    "assembly_failed",
    "guidance_failed",
    "cancelled",
    "interrupted",
]


class SourceGuide(RetrievalValue):
    question: NonemptyText
    status: GuideOutcome | Literal["running"]
    assessment: QuestionAssessment | None = None
    message: NonemptyText | None = None
    articles: tuple[GuideArticle, ...] = ()
    groups: tuple[ArticleGroup, ...] = ()
    relevance_order: tuple[str, ...] = ()
    partial: bool = False


class GuideAttempt(RetrievalValue):
    attempt_id: str
    started_at: datetime
    finished_at: datetime | None = None
    status: Literal[
        "running", "completed", "empty", "failed", "cancelled", "interrupted"
    ]
    outcome: GuideOutcome | None = None
    assessment: QuestionAssessment | None = None
    message: NonemptyText | None = None


class SavedSourceGuide(SourceGuide):
    guide_id: str
    created_at: datetime
    latest_attempt: GuideAttempt
    last_retrieved_at: datetime | None = None
