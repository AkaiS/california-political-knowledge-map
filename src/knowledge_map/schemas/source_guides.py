"""Reader-facing Source Guide values contain citations and directions only."""

from typing import Literal

from knowledge_map.schemas.query_preparation import QuestionAssessment
from knowledge_map.schemas.retrieval import (
    NonemptyText,
    RetrievalValue,
    SourceArticleCitation,
)


class GuideArticle(RetrievalValue):
    citation: SourceArticleCitation
    reading_direction: NonemptyText


class SourceGuide(RetrievalValue):
    question: NonemptyText
    status: Literal[
        "completed",
        "empty",
        "declined",
        "needs_edit",
        "assessment_failed",
        "retrieval_failed",
        "assembly_failed",
        "guidance_failed",
    ]
    assessment: QuestionAssessment | None = None
    message: NonemptyText | None = None
    articles: tuple[GuideArticle, ...] = ()
    partial: bool = False
