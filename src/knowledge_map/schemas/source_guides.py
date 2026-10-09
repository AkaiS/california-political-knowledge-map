"""Reader-facing citations, directions, and verified navigation without chunk bodies."""

from datetime import date, datetime
from typing import Literal

from pydantic import HttpUrl

from knowledge_map.schemas.query_preparation import QuestionAssessment
from knowledge_map.schemas.retrieval import (
    ArticleGroup,
    Count,
    NonemptyText,
    RetrievalValue,
    SourceArticleCitation,
)


class GuideArticle(RetrievalValue):
    citation: SourceArticleCitation
    reading_direction: NonemptyText
    publication: NonemptyText | None = None
    section_links: tuple[HttpUrl, ...] = ()


class GuideCollection(RetrievalValue):
    name: NonemptyText
    date_basis: Literal["publication_date", "event_date"]
    earliest_date: date | None = None
    latest_date: date | None = None


class GuideSearchDetails(RetrievalValue):
    collections: tuple[GuideCollection, ...] = ()
    completion: Literal[
        "running",
        "completed",
        "partial",
        "failed",
        "not_searched",
        "cancelled",
        "interrupted",
    ] = "running"
    bounded_selection: bool = True
    selection_limited: bool = False
    included_articles: Count = 0


class GuideDisclosure(RetrievalValue):
    kind: Literal[
        "unmatched_request",
        "partial_search",
        "deferred",
        "declined",
        "needs_edit",
        "no_matches",
        "irrelevant_candidates",
        "retrieval_failed",
        "assembly_failed",
        "guidance_failed",
        "assessment_failed",
    ]
    message: NonemptyText
    request_portion: NonemptyText | None = None


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
    search_details: GuideSearchDetails | None = None
    disclosures: tuple[GuideDisclosure, ...] = ()


class GuideAttemptSummary(RetrievalValue):
    attempt_id: str
    started_at: datetime
    finished_at: datetime | None = None
    status: Literal[
        "running", "completed", "empty", "failed", "cancelled", "interrupted"
    ]
    outcome: GuideOutcome | None = None
    assessment: QuestionAssessment | None = None


class GuideAttempt(GuideAttemptSummary):
    message: NonemptyText | None = None
    search_details: GuideSearchDetails | None = None
    disclosures: tuple[GuideDisclosure, ...] = ()


class SavedGuideSummary(RetrievalValue):
    guide_id: str
    question: NonemptyText
    status: GuideOutcome | Literal["running"]
    created_at: datetime
    latest_attempt: GuideAttemptSummary
    last_retrieved_at: datetime | None = None


class SavedSourceGuide(SourceGuide):
    guide_id: str
    created_at: datetime
    latest_attempt: GuideAttempt
    last_retrieved_at: datetime | None = None
