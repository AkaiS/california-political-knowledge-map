"""Question preparation values shared by the Chat Agent and retrieval."""

from datetime import date
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StringConstraints,
    model_validator,
)

type QuestionText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1)
]
type ReadingOrder = Literal[
    "relevance", "publication_asc", "publication_desc", "event_asc", "event_desc"
]


class QueryRewriteProposal(BaseModel):
    """One proposed question and its internal structural-retrieval route."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    question: QuestionText
    relational: StrictBool


class QuestionAssessment(BaseModel):
    """The Chat Agent's question-policy and coverage decision."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["allowed", "declined", "deferred", "needs_edit"]
    explanation: QuestionText | None = None
    recoverable_portion: QuestionText | None = None
    reading_order: ReadingOrder = "relevance"
    publication_date_from: date | None = None
    publication_date_through: date | None = None

    @model_validator(mode="after")
    def publication_bounds_are_chronological(self) -> Self:
        if (
            self.publication_date_from is not None
            and self.publication_date_through is not None
            and self.publication_date_from > self.publication_date_through
        ):
            raise ValueError("publication date bounds must be chronological")
        return self

    @model_validator(mode="after")
    def unsupported_question_has_explanation(self) -> Self:
        if self.status != "allowed" and self.explanation is None:
            raise ValueError(
                "a Declined, Deferred, or needs-edit question requires an explanation"
            )
        if self.status == "deferred" and self.recoverable_portion is None:
            raise ValueError(
                "a Deferred question must describe the recoverable portion"
            )
        return self


class QueryApproval(BaseModel):
    """The user-facing question, with no internal retrieval route."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    question: QuestionText
    explanation: QuestionText | None = None
    recoverable_portion: QuestionText | None = None


class AwaitingQueryApproval(BaseModel):
    """A proposed question that the Chat Agent may present for approval."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["awaiting_approval"] = "awaiting_approval"
    approval: QueryApproval


class DeclinedQuestion(BaseModel):
    """A policy-declined question that cannot proceed to approval."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["declined"] = "declined"
    message: QuestionText


class RewriteUnavailable(BaseModel):
    """A temporary Query Rewriter failure that prevents approval."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["rewrite_unavailable"] = "rewrite_unavailable"
    message: QuestionText


type QuestionPreparationResult = Annotated[
    AwaitingQueryApproval | DeclinedQuestion | RewriteUnavailable,
    Field(discriminator="status"),
]


class QueryRewrite(QueryRewriteProposal):
    """The user-approved retrieval input, retaining the coverage decision."""

    assessment: QuestionAssessment


class RewriteRejection(QueryRewriteProposal):
    """The rejected proposal and the feedback for another rewrite attempt."""

    outcome: Literal["rewrite_rejected"] = "rewrite_rejected"
    correction: str | None = None
