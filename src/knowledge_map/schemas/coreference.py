from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator


class MentionSpan(BaseModel):
    """A model-returned reference anchored to a numbered sentence.

    The model supplies only the sentence label, the verbatim mention, the
    occurrence of that mention within the sentence, and its canonical entity.
    Character positions deliberately do not belong to this schema: they are
    derived from the source content by the coreference adapter.
    """

    model_config = ConfigDict(extra="forbid")

    sentence_label: str = Field(
        ...,
        min_length=1,
        validation_alias=AliasChoices("sentence_label", "sentence"),
        description="The label of the numbered sentence containing the mention.",
    )
    mention_text: str = Field(
        ...,
        min_length=1,
        validation_alias=AliasChoices("mention_text", "mention"),
        description="The mention exactly as it appears in the numbered sentence.",
    )
    occurrence: int = Field(
        default=1,
        ge=1,
        validation_alias=AliasChoices("occurrence", "occurrence_number"),
        description="One-based occurrence of the mention text within the sentence.",
    )
    canonical_entity_name: str = Field(
        ...,
        min_length=1,
        validation_alias=AliasChoices(
            "canonical_entity_name",
            "canonical_entity",
            "entity_name",
            "entity",
        ),
        description="The canonical name of the entity the mention refers to.",
    )

    @property
    def sentence(self) -> str:
        """Return the sentence label using the concise domain name."""

        return self.sentence_label

    @property
    def mention(self) -> str:
        """Return the verbatim mention text using the concise domain name."""

        return self.mention_text

    @property
    def occurrence_number(self) -> int:
        """Return the one-based occurrence number."""

        return self.occurrence

    @property
    def canonical_entity(self) -> str:
        """Return the canonical entity name using the concise domain name."""

        return self.canonical_entity_name


class MentionSpanDiscard(BaseModel):
    """A Mention Span rejected by deterministic validation."""

    model_config = ConfigDict(frozen=True)

    mention_span: MentionSpan
    reason: str = Field(..., min_length=1)


class CriticVerdict(BaseModel):
    """The Coreference Critic's decision for one validated Mention Span."""

    model_config = ConfigDict(extra="forbid")

    sentence_label: str = Field(
        ...,
        min_length=1,
        validation_alias=AliasChoices("sentence_label", "sentence"),
        description="The label of the numbered sentence containing the mention.",
    )
    mention_text: str = Field(
        ...,
        min_length=1,
        validation_alias=AliasChoices("mention_text", "mention"),
        description="The verbatim mention text being judged.",
    )
    occurrence: int = Field(
        default=1,
        ge=1,
        validation_alias=AliasChoices("occurrence", "occurrence_number"),
        description="The one-based occurrence of the mention within its sentence.",
    )
    accepted: bool = Field(
        ...,
        validation_alias=AliasChoices(
            "accepted",
            "is_accepted",
            "accept",
            "is_valid",
        ),
        description="Whether the Mention Span's canonical entity is correct.",
    )
    reason: str | None = Field(
        default=None,
        validation_alias=AliasChoices("reason", "rejection_reason"),
        description="A short explanation required when the Mention Span is rejected.",
    )

    @model_validator(mode="after")
    def require_rejection_reason(self) -> "CriticVerdict":
        """Require an explanation whenever the critic rejects a span."""

        if not self.accepted and (self.reason is None or not self.reason.strip()):
            raise ValueError("reason is required when a Mention Span is rejected")
        return self

    @property
    def is_accepted(self) -> bool:
        """Return the decision using the explicit predicate spelling."""

        return self.accepted

    @property
    def is_valid(self) -> bool:
        """Return the decision using the critic's former predicate wording."""

        return self.accepted


# The domain name is useful to callers that want to emphasize the judged unit.
MentionSpanVerdict = CriticVerdict
