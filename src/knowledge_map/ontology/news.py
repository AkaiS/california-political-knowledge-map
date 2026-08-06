"""The closed ontology of structures the news pipeline can produce."""

from dataclasses import dataclass

from .primary import PROPERTIES as PRIMARY_PROPERTIES
from .primary import RelationshipShape


@dataclass(frozen=True)
class PolicyArea:
    id: str
    name: str


@dataclass(frozen=True)
class ShortcutRule:
    """A direct news edge that collapses a path in the primary ontology."""

    relationship_type: str
    source_label: str
    target_label: str
    path: tuple[tuple[str, str, str], ...]
    skips: str


LABELS = frozenset(
    {
        "NewsArticle", "Chunk", "PolicyArea", "Politician", "Committee", "Bill",
        "LegislativeEvent", "Prop", "Campaign", "Organization",
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

REQUIRED_SUB_LABELS = frozenset({"LegislativeEvent", "Campaign"})

PROPERTIES = {label: PRIMARY_PROPERTIES[label] for label in LABELS}

POLICY_AREAS = (
    PolicyArea("aging-and-long-term-care", "Aging & Long-Term Care"),
    PolicyArea("agriculture", "Agriculture"),
    PolicyArea("arts-entertainment-and-tourism", "Arts, Entertainment & Tourism"),
    PolicyArea("banking-and-finance", "Banking & Finance"),
    PolicyArea("business-and-professions", "Business & Professions"),
    PolicyArea("economic-development", "Economic Development"),
    PolicyArea("education", "Education (K–12)"),
    PolicyArea("emergency-management", "Emergency Management"),
    PolicyArea("energy-and-utilities", "Energy & Utilities"),
    PolicyArea("environment-and-natural-resources", "Environment & Natural Resources"),
    PolicyArea("government-operations", "Government Operations"),
    PolicyArea("health", "Health"),
    PolicyArea("higher-education", "Higher Education"),
    PolicyArea("housing", "Housing & Community Development"),
    PolicyArea("human-services", "Human Services"),
    PolicyArea("insurance", "Insurance"),
    PolicyArea("judiciary", "Judiciary"),
    PolicyArea("labor", "Labor & Employment"),
    PolicyArea("local-government", "Local Government"),
    PolicyArea("privacy-and-consumer-protection", "Privacy & Consumer Protection"),
    PolicyArea("public-employment-and-pensions", "Public Employment & Pensions"),
    PolicyArea("public-safety", "Public Safety"),
    PolicyArea("taxation", "Revenue & Taxation"),
    PolicyArea("technology", "Technology & Communications"),
    PolicyArea("transportation", "Transportation"),
    PolicyArea("veterans-and-military-affairs", "Veterans' & Military Affairs"),
    PolicyArea("water", "Water"),
)

_SHORTCUT_TARGETS = {
    "VOTED_AYE": "LegislativeEvent",
    "VOTED_NO": "LegislativeEvent",
    "ABSTAINED": "LegislativeEvent",
    "SERVES_ON": "Committee",
    "CHAIRS": "Committee",
    "VICE_CHAIRS": "Committee",
}

SHORTCUTS = tuple(
    ShortcutRule(
        relationship_type=relationship_type,
        source_label="Politician",
        target_label=target_label,
        path=(
            ("Politician", "HELD_TENURE", "LegislativeTenure"),
            ("LegislativeTenure", relationship_type, target_label),
        ),
        skips="LegislativeTenure",
    )
    for relationship_type, target_label in _SHORTCUT_TARGETS.items()
)

RELATIONSHIPS = {
    "SERVES_ON": RelationshipShape(frozenset({"Politician"}), frozenset({"Committee"})),
    "CHAIRS": RelationshipShape(frozenset({"Politician"}), frozenset({"Committee"})),
    "VICE_CHAIRS": RelationshipShape(frozenset({"Politician"}), frozenset({"Committee"})),
    "VOTED_AYE": RelationshipShape(frozenset({"Politician"}), frozenset({"LegislativeEvent"})),
    "VOTED_NO": RelationshipShape(frozenset({"Politician"}), frozenset({"LegislativeEvent"})),
    "ABSTAINED": RelationshipShape(frozenset({"Politician"}), frozenset({"LegislativeEvent"})),
    "ACTION_ON": RelationshipShape(frozenset({"LegislativeEvent"}), frozenset({"Bill"})),
    "ABOUT_TOPIC": RelationshipShape(frozenset({"Bill", "Prop"}), frozenset({"PolicyArea"})),
    "CAMPAIGN_FOR": RelationshipShape(frozenset({"Campaign"}), frozenset({"Prop", "Politician"})),
    "FUNDED": RelationshipShape(frozenset({"Organization"}), frozenset({"Campaign"})),
    "LOBBIED_FOR": RelationshipShape(frozenset({"Organization"}), frozenset({"Bill"})),
    "LOBBIED_AGAINST": RelationshipShape(frozenset({"Organization"}), frozenset({"Bill"})),
    "ENDORSED": RelationshipShape(frozenset({"Politician", "Organization"}), frozenset({"Prop", "Campaign"})),
    "DENOUNCED": RelationshipShape(frozenset({"Politician", "Organization"}), frozenset({"Prop", "Campaign"})),
    "DECLARED_STANCE": RelationshipShape(frozenset({"Politician", "Organization"}), frozenset({"Prop", "Bill"})),
    "HAS_CHUNK": RelationshipShape(frozenset({"NewsArticle"}), frozenset({"Chunk"})),
    "MENTIONED_IN": RelationshipShape(
        frozenset({"Politician", "Committee", "Bill", "LegislativeEvent", "Prop", "Campaign", "Organization"}),
        frozenset({"Chunk"}),
    ),
    "DISCUSSES_TOPIC": RelationshipShape(frozenset({"NewsArticle", "Chunk"}), frozenset({"PolicyArea"})),
}
