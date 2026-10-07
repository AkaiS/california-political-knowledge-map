"""Small model-facing contract for ontology-composable retrieval patterns."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class NodeLabel(StrEnum):
    POLITICIAN = "Politician"
    ORGANIZATION = "Organization"
    LABOR_UNION = "LaborUnion"
    PAC = "PAC"
    BILL = "Bill"
    PROP = "Prop"
    CAMPAIGN = "Campaign"
    LEGISLATIVE_EVENT = "LegislativeEvent"
    COMMITTEE = "Committee"
    NEWS_ARTICLE = "NewsArticle"
    CHUNK = "Chunk"
    POLICY_AREA = "PolicyArea"


class Predicate(StrEnum):
    MENTIONED_IN = "MENTIONED_IN"
    HAS_CHUNK = "HAS_CHUNK"
    DISCUSSES_TOPIC = "DISCUSSES_TOPIC"
    DECLARED_STANCE = "DECLARED_STANCE"
    ENDORSED = "ENDORSED"
    LOBBIED_FOR = "LOBBIED_FOR"
    LOBBIED_AGAINST = "LOBBIED_AGAINST"
    ABOUT_TOPIC = "ABOUT_TOPIC"
    FUNDED = "FUNDED"
    CAMPAIGN_FOR = "CAMPAIGN_FOR"
    VOTED_AYE = "VOTED_AYE"
    VOTED_NO = "VOTED_NO"
    ABSTAINED = "ABSTAINED"
    ACTION_ON = "ACTION_ON"
    REFERRED_TO = "REFERRED_TO"


class PropertyName(StrEnum):
    ID = "id"
    NAME = "name"
    SESSION = "session"
    TITLE = "title"
    PUBLISHED_DATE = "published_date"


class ConstraintOperator(StrEnum):
    EQ = "eq"
    DATE_GTE = "date_gte"
    DATE_LT = "date_lt"


class NodeVar(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    label: NodeLabel


class Triple(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subject: str
    predicates: list[Predicate] = Field(min_length=1)
    object: str
    claim_name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")

    @model_validator(mode="after")
    def unique_predicates(self):
        if len(set(self.predicates)) != len(self.predicates):
            raise ValueError("triple predicates must be unique")
        return self


class Constraint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    variable: str
    property: PropertyName
    operator: ConstraintOperator = ConstraintOperator.EQ
    slot: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    description: str


class Inequality(BaseModel):
    model_config = ConfigDict(extra="forbid")
    left_variable: str
    right_variable: str
    property: PropertyName = PropertyName.ID


class ReturnTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")
    variable: str
    fields: list[PropertyName] = Field(min_length=1)


class Aggregate(BaseModel):
    """The only aggregate needed by this batch."""

    model_config = ConfigDict(extra="forbid")
    group_variable: str
    count_distinct_variable: str
    collect_distinct_variable: str


class PatternPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    nodes: list[NodeVar] = Field(min_length=2)
    triples: list[Triple] = Field(min_length=1)
    constraints: list[Constraint]
    inequalities: list[Inequality]
    return_targets: list[ReturnTarget] = Field(min_length=1)
    aggregate: Aggregate | None
    rationale: str


NODE_PROPERTIES = {label: {PropertyName.ID, PropertyName.NAME} for label in NodeLabel}
NODE_PROPERTIES[NodeLabel.BILL].add(PropertyName.SESSION)
NODE_PROPERTIES[NodeLabel.NEWS_ARTICLE] = {
    PropertyName.ID,
    PropertyName.TITLE,
    PropertyName.PUBLISHED_DATE,
}
NODE_PROPERTIES[NodeLabel.CHUNK] = {PropertyName.ID}
