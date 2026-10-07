"""Model-facing contracts that contain semantic choices only."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SemanticLabel = Literal[
    "Politician",
    "Organization",
    "LaborUnion",
    "PAC",
    "Bill",
    "Prop",
    "Campaign",
    "LegislativeEvent",
    "Committee",
    "PolicyArea",
]
SemanticPredicate = Literal[
    "DISCUSSES_TOPIC",
    "DECLARED_STANCE",
    "ENDORSED",
    "LOBBIED_FOR",
    "LOBBIED_AGAINST",
    "ABOUT_TOPIC",
    "FUNDED",
    "CAMPAIGN_FOR",
    "VOTED_AYE",
    "VOTED_NO",
    "ABSTAINED",
    "ACTION_ON",
    "REFERRED_TO",
]
FilterProperty = Literal["name", "session", "title", "published_date"]


class SemanticSchemaSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    labels: list[SemanticLabel]
    relationships: list[SemanticPredicate]
    filter_properties: dict[str, list[FilterProperty]] = Field(default_factory=dict)
    rationale: str


class PieceSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role_ids: list[str] = Field(default_factory=list, max_length=8)
    relationship_ids: list[str] = Field(default_factory=list, max_length=8)
    filter_ids: list[str] = Field(default_factory=list, max_length=8)
    role_constraint_ids: list[str] = Field(default_factory=list, max_length=4)
    aggregation_ids: list[str] = Field(default_factory=list, max_length=2)

    @property
    def all_ids(self) -> list[str]:
        return [
            *self.role_ids,
            *self.relationship_ids,
            *self.filter_ids,
            *self.role_constraint_ids,
            *self.aggregation_ids,
        ]


class TripleWiring(BaseModel):
    model_config = ConfigDict(extra="forbid")

    relationship_index: int = Field(ge=0)
    source_role_index: int = Field(ge=0)
    target_role_index: int = Field(ge=0)


class FilterWiring(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filter_index: int = Field(ge=0)
    role_index: int = Field(ge=0)


class DistinctRoleWiring(BaseModel):
    model_config = ConfigDict(extra="forbid")

    constraint_index: int = Field(ge=0)
    left_role_index: int = Field(ge=0)
    right_role_index: int = Field(ge=0)


class AggregateWiring(BaseModel):
    model_config = ConfigDict(extra="forbid")

    aggregation_index: int = Field(ge=0)
    group_role_index: int = Field(ge=0)
    count_role_index: int = Field(ge=0)


class ComposerWiring(BaseModel):
    """Model-owned wiring for selected non-aggregate semantic occurrences."""

    model_config = ConfigDict(extra="forbid")

    triples: list[TripleWiring]
    filters: list[FilterWiring]
    distinct_roles: list[DistinctRoleWiring]
    rationale: str


class SemanticWiring(BaseModel):
    """Numeric wiring for already-selected semantic piece occurrences."""

    model_config = ConfigDict(extra="forbid")

    triples: list[TripleWiring]
    filters: list[FilterWiring]
    distinct_roles: list[DistinctRoleWiring]
    aggregate: AggregateWiring | None
    rationale: str


class PositionalBindings(BaseModel):
    """Question values in the compiler-declared order, without parameter names."""

    model_config = ConfigDict(extra="forbid")

    values: list[str] = Field(max_length=8)
