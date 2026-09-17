"""Question preparation values shared by the Chat Agent and retrieval."""

from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    StrictBool,
    StringConstraints,
    model_validator,
)

type QuestionText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1)
]


class QueryRewrite(BaseModel):
    """One proposed question and its internal structural-retrieval route."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    question: QuestionText
    relational: StrictBool


class QuestionAssessment(BaseModel):
    """The Chat Agent's question-policy and coverage decision."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["allowed", "declined", "deferred"]
    explanation: QuestionText | None = None
    recoverable_portion: QuestionText | None = None

    @model_validator(mode="after")
    def unsupported_question_has_explanation(self) -> Self:
        if self.status != "allowed" and self.explanation is None:
            raise ValueError("a Declined or Deferred question requires an explanation")
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


class QuestionPreparationResult(BaseModel):
    """The presentation returned to the Chat Agent before retrieval."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["awaiting_approval", "declined", "rewrite_unavailable"]
    approval: QueryApproval | None = None
    message: str | None = None


class ApprovedQueryRewrite(QueryRewrite):
    """The approved retrieval input, retaining the coverage decision."""

    assessment: QuestionAssessment


class RewriteRejection(QueryRewrite):
    """The rejected proposal and the feedback for another rewrite attempt."""

    outcome: Literal["rewrite_rejected"] = "rewrite_rejected"
    correction: str | None = None
