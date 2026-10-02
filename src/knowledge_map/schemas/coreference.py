from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from knowledge_map.prompts import load_prompt


def _strip_label_brackets(value: object) -> object:
    """Normalise a sentence label the model copied verbatim from its prompt.

    The sentence table is rendered as ``[1] ...``, so an annotator commonly
    answers with ``"[1]"`` where the label itself is ``"1"``. Both spellings
    name the same sentence.
    """

    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if stripped.startswith("[") and stripped.endswith("]"):
        stripped = stripped[1:-1].strip()
    return stripped


class MentionSpan(BaseModel):
    """A model-returned reference anchored to a numbered sentence.

    Carries no character positions; the coreference adapter derives those from
    the source content.
    """

    model_config = ConfigDict(extra="forbid")

    sentence_label: str = Field(
        ...,
        min_length=1,
        description=load_prompt("coreference/sentence-label-guidance", version=1),
    )
    mention_text: str = Field(
        ...,
        min_length=1,
        description=load_prompt("coreference/mention-text-guidance", version=1),
    )
    occurrence: int = Field(
        default=1,
        ge=1,
        description=load_prompt("coreference/occurrence-guidance", version=1),
    )
    canonical_entity_name: str = Field(
        ...,
        min_length=1,
        description="The canonical name of the entity the mention refers to.",
    )

    @field_validator("sentence_label", mode="before")
    @classmethod
    def normalise_sentence_label(cls, value: object) -> object:
        """Accept the bracketed label the sentence table displays."""

        return _strip_label_brackets(value)


class MentionSpanDiscard(BaseModel):
    """A Mention Span rejected by deterministic validation."""

    model_config = ConfigDict(frozen=True)

    mention_span: MentionSpan
    reason: str = Field(..., min_length=1)


class NumberedSentenceRecord(BaseModel):
    """A numbered sentence retained as part of one resolution run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    label: str = Field(..., min_length=1)
    text: str
    start_index: int = Field(..., ge=0)
    end_index: int = Field(..., ge=0)

class MentionSpanOutcome(BaseModel):
    """The final observed outcome for one model-returned Mention Span."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    mention_span: MentionSpan
    stage: Literal["validation", "critic"]
    outcome: Literal["accepted", "discarded", "rejected"]
    reason: str | None = None

    @model_validator(mode="after")
    def require_reason_for_non_acceptance(self) -> "MentionSpanOutcome":
        """Require an audit reason whenever a span does not survive."""

        if self.outcome != "accepted" and (
            self.reason is None or not self.reason.strip()
        ):
            raise ValueError("reason is required for a discarded or rejected span")
        return self

    @property
    def accepted(self) -> bool:
        """Whether this Mention Span survived resolution."""

        return self.outcome == "accepted"


class CoreferenceResolutionRun(BaseModel):
    """Observable output and quality counters for one resolution attempt."""

    model_config = ConfigDict(extra="forbid")

    resolved_text: str
    sentences: list[NumberedSentenceRecord] = Field(default_factory=list)
    mention_spans: list[MentionSpan] = Field(default_factory=list)
    outcomes: list[MentionSpanOutcome] = Field(default_factory=list)
    discarded_proportion: float = Field(..., ge=0.0, le=1.0)
    retry_count: int = Field(default=0, ge=0)
    failure_type: str | None = None

    @property
    def discarded_count(self) -> int:
        """Return how many observed Mention Spans did not survive."""

        return sum(not outcome.accepted for outcome in self.outcomes)

    @property
    def surviving_spans(self) -> list[MentionSpan]:
        """Return the Mention Spans accepted by the Coreference Critic."""

        return [
            outcome.mention_span
            for outcome in self.outcomes
            if outcome.accepted
        ]


class CriticVerdict(BaseModel):
    """The Coreference Critic's decision for one validated Mention Span."""

    model_config = ConfigDict(extra="forbid")

    sentence_label: str = Field(
        ...,
        min_length=1,
        description=load_prompt("coreference/sentence-label-guidance", version=1),
    )
    mention_text: str = Field(
        ...,
        min_length=1,
        description=load_prompt("coreference/verdict-mention-guidance", version=1),
    )
    occurrence: int = Field(
        default=1,
        ge=1,
        description=load_prompt("coreference/verdict-occurrence-guidance", version=1),
    )
    accepted: bool = Field(
        ...,
        description="Whether the Mention Span's canonical entity is correct.",
    )
    reason: str | None = Field(
        default=None,
        description=load_prompt("coreference/verdict-reason-guidance", version=1),
    )

    @field_validator("sentence_label", mode="before")
    @classmethod
    def normalise_sentence_label(cls, value: object) -> object:
        """Accept the bracketed label the sentence table displays."""

        return _strip_label_brackets(value)

    @model_validator(mode="after")
    def require_rejection_reason(self) -> "CriticVerdict":
        """Require an explanation whenever the critic rejects a span."""

        if not self.accepted and (self.reason is None or not self.reason.strip()):
            raise ValueError("reason is required when a Mention Span is rejected")
        return self
