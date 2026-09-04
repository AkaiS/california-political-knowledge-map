"""Machine-readable mirror of the repository's primary ``ontology.md``."""

from dataclasses import dataclass, field

from .properties import (
    PropertySpec, enum_spec, normalize_amount, normalize_date, normalize_text
)


@dataclass(frozen=True)
class RelationshipShape:
    """Permitted endpoint labels for one primary-ontology relationship.

    ``properties`` is the whitelist conformance reads — an undeclared property
    is dropped, never written — and fixes each declared property's canonical
    shape.
    """

    source_labels: frozenset[str]
    target_labels: frozenset[str]
    properties: tuple[PropertySpec, ...] = field(default=())

    @property
    def property_names(self) -> frozenset[str]:
        return frozenset(spec.name for spec in self.properties)

    def spec(self, name: str) -> PropertySpec | None:
        return next((spec for spec in self.properties if spec.name == name), None)


#: Declared in the relationship table of ``ontology.md``.
_FUNDED_PROPERTIES = (
    PropertySpec(
        "amount", normalize_amount,
        form="a dollar figure, either digits (`6000000`) or a magnitude phrase (`$6 million`)",
        example="$6 million",
    ),
    PropertySpec(
        "date", normalize_date,
        form="a calendar date as `YYYY-MM-DD`; a year alone is not a date",
        example="2024-01-15",
    ),
    PropertySpec(
        "transaction_id", normalize_text,
        form="the filing identifier exactly as printed", example="FPPC-2024-0198",
    ),
)
#: A stance's direction is entailed by the stance: prose that states support or
#: opposition has stated which, and `NEUTRAL` covers the hedged case, so the
#: vocabulary is total and nothing is left for the model to invent.
_STANCE_PROPERTIES = (
    enum_spec("alignment", "POSITIVE", "NEGATIVE", "NEUTRAL", entailed=True),
)


LABELS = frozenset(
    {
        "NewsArticle", "Chunk", "PolicyArea", "Politician",
        "LegislativeTenure", "District", "RedistrictingCycle", "Committee",
        "Bill", "LegislativeEvent", "Prop", "Campaign", "Organization",
        "ExternalIdentifier",
    }
)

SUB_LABELS = {
    "LegislativeEvent": frozenset({"Vote", "Amendment", "Hearing"}),
    "Campaign": frozenset({"CandidateCampaign", "BallotMeasureCampaign"}),
    "Organization": frozenset(
        {
            "PAC", "IE_Committee", "Corporation", "LaborUnion",
            "TradeAssociation", "NonProfit", "AdvocacyGroup",
            "GrassrootsMovement", "TribalNation", "GovernmentAgency",
            "MediaOrganization", "EducationalInstitution",
        }
    ),
}

PROPERTIES = {
    "NewsArticle": frozenset({"id", "title", "author", "publisher", "published_date", "summary"}),
    "Chunk": frozenset({"id", "text", "embedding", "index"}),
    "PolicyArea": frozenset({"id", "name", "embedding"}),
    "Politician": frozenset({"id", "first_name", "last_name", "birth_date", "current_party"}),
    "LegislativeTenure": frozenset({"id", "chamber", "start_year", "end_year", "party_affiliation"}),
    "District": frozenset({"id", "number", "cycle_year"}),
    "RedistrictingCycle": frozenset({"id", "year", "mid_cycle"}),
    "Committee": frozenset({"id", "name", "chamber"}),
    "Bill": frozenset({"id", "name", "session", "current_status"}),
    "LegislativeEvent": frozenset({"id", "type", "date", "sequence_number", "description"}),
    "Prop": frozenset({"id", "number", "election_date", "official_title", "summary"}),
    "Campaign": frozenset({"id", "name", "election_cycle", "status"}),
    "Organization": frozenset({"id", "name", "industry_sector", "fppc_id"}),
    "ExternalIdentifier": frozenset({"scheme", "value", "source", "source_url", "verified_at", "status"}),
}

CORE_ENTITY_LABELS = frozenset(
    LABELS - {"NewsArticle", "Chunk", "PolicyArea", "ExternalIdentifier"}
)


def _shape(
    source: str | frozenset[str],
    target: str | frozenset[str],
    properties: tuple[PropertySpec, ...] = (),
) -> RelationshipShape:
    sources = frozenset({source}) if isinstance(source, str) else source
    targets = frozenset({target}) if isinstance(target, str) else target
    return RelationshipShape(sources, targets, properties)


RELATIONSHIPS = {
    "HELD_TENURE": _shape("Politician", "LegislativeTenure"),
    "REPRESENTS_DISTRICT": _shape("LegislativeTenure", "District"),
    "TRANSITIONED_BY": _shape("District", "RedistrictingCycle"),
    "EVOLVED_INTO": _shape("RedistrictingCycle", "District"),
    "SERVES_ON": _shape("LegislativeTenure", "Committee"),
    "CHAIRS": _shape("LegislativeTenure", "Committee"),
    "VICE_CHAIRS": _shape("LegislativeTenure", "Committee"),
    "VOTED_AYE": _shape("LegislativeTenure", "LegislativeEvent"),
    "VOTED_NO": _shape("LegislativeTenure", "LegislativeEvent"),
    "ABSTAINED": _shape("LegislativeTenure", "LegislativeEvent"),
    "ACTION_ON": _shape("LegislativeEvent", "Bill"),
    "HELD_BY": _shape("LegislativeEvent", "Committee"),
    "REFERRED_TO": _shape("Bill", "Committee"),
    "ABOUT_TOPIC": _shape(frozenset({"Bill", "Prop"}), "PolicyArea"),
    "CAMPAIGN_FOR": _shape("Campaign", frozenset({"Prop", "Politician"})),
    "FUNDED": _shape("Organization", "Campaign", _FUNDED_PROPERTIES),
    "LOBBIED_FOR": _shape("Organization", "Bill"),
    "LOBBIED_AGAINST": _shape("Organization", "Bill"),
    "ENDORSED": _shape(frozenset({"Politician", "Organization"}), frozenset({"Prop", "Campaign"})),
    "DENOUNCED": _shape(frozenset({"Politician", "Organization"}), frozenset({"Prop", "Campaign"})),
    "DECLARED_STANCE": _shape(
        frozenset({"Politician", "Organization"}), frozenset({"Prop", "Bill"}), _STANCE_PROPERTIES
    ),
    "HAS_CHUNK": _shape("NewsArticle", "Chunk"),
    "MENTIONED_IN": _shape(CORE_ENTITY_LABELS, "Chunk"),
    "DISCUSSES_TOPIC": _shape(frozenset({"NewsArticle", "Chunk"}), "PolicyArea"),
    "HAS_IDENTIFIER": _shape(CORE_ENTITY_LABELS, "ExternalIdentifier"),
}
