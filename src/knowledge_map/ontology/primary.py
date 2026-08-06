"""Machine-readable mirror of the repository's primary ``ontology.md``."""

from dataclasses import dataclass


@dataclass(frozen=True)
class RelationshipShape:
    """Permitted endpoint labels for one primary-ontology relationship."""

    source_labels: frozenset[str]
    target_labels: frozenset[str]


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
            "MediaOrganization",
        }
    ),
}

PROPERTIES = {
    "NewsArticle": frozenset({"id", "title", "publisher", "publish_date", "summary"}),
    "Chunk": frozenset({"id", "text", "embedding", "index"}),
    "PolicyArea": frozenset({"id", "name", "embedding"}),
    "Politician": frozenset({"id", "first_name", "last_name", "birth_date", "current_party"}),
    "LegislativeTenure": frozenset({"id", "chamber", "start_year", "end_year", "party_affiliation"}),
    "District": frozenset({"id", "number", "cycle_year"}),
    "RedistrictingCycle": frozenset({"id", "year", "mid_cycle"}),
    "Committee": frozenset({"id", "name", "chamber"}),
    "Bill": frozenset({"id", "number", "session", "current_status"}),
    "LegislativeEvent": frozenset({"id", "type", "date", "description"}),
    "Prop": frozenset({"id", "number", "election_date", "official_title", "summary"}),
    "Campaign": frozenset({"id", "name", "election_cycle", "status"}),
    "Organization": frozenset({"id", "name", "industry_sector", "fppc_id"}),
    "ExternalIdentifier": frozenset({"scheme", "value", "source", "source_url", "verified_at", "status"}),
}

CORE_ENTITY_LABELS = frozenset(
    LABELS - {"NewsArticle", "Chunk", "PolicyArea", "ExternalIdentifier"}
)
RESOLVABLE_CORE_ENTITY_LABELS = CORE_ENTITY_LABELS


def _shape(source: str | frozenset[str], target: str | frozenset[str]) -> RelationshipShape:
    sources = frozenset({source}) if isinstance(source, str) else source
    targets = frozenset({target}) if isinstance(target, str) else target
    return RelationshipShape(sources, targets)


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
    "ABOUT_TOPIC": _shape(frozenset({"Bill", "Prop"}), "PolicyArea"),
    "CAMPAIGN_FOR": _shape("Campaign", frozenset({"Prop", "Politician"})),
    "FUNDED": _shape("Organization", "Campaign"),
    "LOBBIED_FOR": _shape("Organization", "Bill"),
    "LOBBIED_AGAINST": _shape("Organization", "Bill"),
    "ENDORSED": _shape(frozenset({"Politician", "Organization"}), frozenset({"Prop", "Campaign"})),
    "DENOUNCED": _shape(frozenset({"Politician", "Organization"}), frozenset({"Prop", "Campaign"})),
    "DECLARED_STANCE": _shape(frozenset({"Politician", "Organization"}), frozenset({"Prop", "Bill"})),
    "HAS_CHUNK": _shape("NewsArticle", "Chunk"),
    "MENTIONED_IN": _shape(CORE_ENTITY_LABELS, "Chunk"),
    "DISCUSSES_TOPIC": _shape(frozenset({"NewsArticle", "Chunk"}), "PolicyArea"),
    "HAS_IDENTIFIER": _shape(RESOLVABLE_CORE_ENTITY_LABELS, "ExternalIdentifier"),
}
