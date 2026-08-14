"""The closed ontology of structures the news pipeline can produce."""

from dataclasses import dataclass, replace

from .divergence import Divergence
from .primary import PROPERTIES as PRIMARY_PROPERTIES
from .primary import RELATIONSHIPS as PRIMARY_RELATIONSHIPS
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

#: Labels the pipeline writes from the article itself, never from model output.
WRITE_PATH_LABELS = frozenset({"NewsArticle", "Chunk"})

#: Labels the extraction model is responsible for producing.
EXTRACTED_LABELS = LABELS - WRITE_PATH_LABELS

NODE_DIVERGENCES = (
    Divergence(
        property_name="name",
        applies_to=frozenset(
            label for label in EXTRACTED_LABELS if "name" not in PRIMARY_PROPERTIES[label]
        ),
        reason=(
            "The extractor identifies an entity by the surface string the article used, "
            "but these labels declare structured fields instead of a `name`. Only entity "
            "resolution against an authoritative record can populate them."
        ),
    ),
    Divergence(
        property_name="session_verified",
        applies_to=frozenset({"Bill"}),
        reason=(
            "A `Bill` id is only stable per legislative session, and news prose rarely "
            "names one. Tier 1 resolves it from a linked authoritative bill page, so the "
            "session is as good as the source and the key is final."
        ),
    ),
    Divergence(
        property_name="session_inferred",
        applies_to=frozenset({"Bill"}),
        reason=(
            "Tier 2 guesses the session from the article's publication date, which is "
            "wrong for a bill discussed outside the session that introduced it. The key "
            "is provisional: only the authoritative session can confirm or re-key it."
        ),
    ),
    Divergence(
        property_name="date_verified",
        applies_to=frozenset({"LegislativeEvent"}),
        reason=(
            "The article stated the date of the event, so the `date` is as good as the "
            "source. It is still not part of the key: the date identifies nothing here, "
            "it is the fact a later reconciliation joins on."
        ),
    ),
    Divergence(
        property_name="date_inferred",
        applies_to=frozenset({"LegislativeEvent"}),
        reason=(
            "The article dated the event no other way, so its publication date stands in. "
            "News usually reports an event within a day or two of it happening, which "
            "makes the stand-in near enough to join on and far too soft to key on."
        ),
    ),
    Divergence(
        property_name="sequence_number",
        applies_to=frozenset({"LegislativeEvent"}),
        reason=(
            "An article reports that a hearing or a vote happened, never where it sat "
            "among the events before it. A single article sees one event, so nothing we "
            "hold can order it against another article's, and only an authoritative "
            "legislative record supplies the position."
        ),
    ),
    Divergence(
        property_name="needs_review",
        applies_to=frozenset({"Bill", "LegislativeEvent"}),
        reason=(
            "For a `Bill`, no session could be resolved or inferred, so the key is a "
            "placeholder that nothing we hold can settle. For a `LegislativeEvent`, "
            "neither the article nor its metadata yielded a date, so the event carries "
            "none and a later reconciliation has nothing to join on."
        ),
    ),
)

#: Property names the model may supply, per label: what the primary ontology
#: declares, less every divergence. One subtraction covers both directions. A
#: property news cannot supply drops out here, which is what makes it absent from
#: the ontology; a property the write path stamps was never in the primary
#: ontology to begin with, so the subtraction is a no-op and the property stays
#: absent. Either way a model that emits one is guessing, and it gets dropped.
PROPERTIES = {
    label: PRIMARY_PROPERTIES[label]
    - frozenset(
        divergence.property_name
        for divergence in NODE_DIVERGENCES
        if label in divergence.applies_to
    )
    for label in LABELS
}

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

#: Shortcuts by the edge they produce. A shortcut edge is reversible from this
#: alone: the rule holds the path it flattened, so expanding one back out needs
#: no further record on the edge beyond the type it already carries.
SHORTCUTS_BY_TYPE = {shortcut.relationship_type: shortcut for shortcut in SHORTCUTS}

_RELATIONSHIP_ENDPOINTS = {
    "SERVES_ON": RelationshipShape(frozenset({"Politician"}), frozenset({"Committee"})),
    "CHAIRS": RelationshipShape(frozenset({"Politician"}), frozenset({"Committee"})),
    "VICE_CHAIRS": RelationshipShape(frozenset({"Politician"}), frozenset({"Committee"})),
    "VOTED_AYE": RelationshipShape(frozenset({"Politician"}), frozenset({"LegislativeEvent"})),
    "VOTED_NO": RelationshipShape(frozenset({"Politician"}), frozenset({"LegislativeEvent"})),
    "ABSTAINED": RelationshipShape(frozenset({"Politician"}), frozenset({"LegislativeEvent"})),
    "ACTION_ON": RelationshipShape(frozenset({"LegislativeEvent"}), frozenset({"Bill"})),
    "HELD_BY": RelationshipShape(frozenset({"LegislativeEvent"}), frozenset({"Committee"})),
    "REFERRED_TO": RelationshipShape(frozenset({"Bill"}), frozenset({"Committee"})),
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

RELATIONSHIP_DIVERGENCES = (
    Divergence(
        property_name="transaction_id",
        applies_to=frozenset({"FUNDED"}),
        reason=(
            "An article reports that money moved, never the FPPC filing that recorded "
            "it. Nothing an article carries identifies the transaction, and only the "
            "disclosure record itself supplies the id."
        ),
    ),
    Divergence(
        property_name="needs_review",
        applies_to=frozenset(
            relationship_type
            for relationship_type in _RELATIONSHIP_ENDPOINTS
            if PRIMARY_RELATIONSHIPS[relationship_type].properties
        ),
        reason=(
            "The article asserted the relationship without a value the claim depends on, "
            "or named one in a form nothing else will match. The edge is real but its key "
            "is incomplete, so it cannot yet be compared against another article's."
        ),
    ),
)

#: News relationships, endpoints as declared above and properties inherited from the
#: primary ontology, less every divergence. Inheriting rather than restating is what
#: keeps the two tables from disagreeing: the extraction prompt asks for exactly the
#: primary ontology's declared properties, so those and only those are the ones a model
#: may attach to an edge. Anything else it supplies is dropped during conformance — a
#: relationship property is write-path-owned, so the only values reaching an edge are
#: ones the system put there deliberately.
#:
#: One subtraction covers both directions, exactly as it does for labels. A property
#: news cannot supply drops out of the Claim Key here, which is what makes it absent
#: from the ontology; a property the write path stamps was never in the primary
#: ontology to begin with, so the subtraction is a no-op and it stays absent. The
#: subtraction is also what stops inheritance from over-reaching: a property the
#: primary ontology declares because an authoritative record supplies it is not
#: thereby one an article can assert, and inheriting it regardless would key every
#: edge on a value no article will ever fill.
RELATIONSHIPS = {
    relationship_type: replace(
        shape,
        properties=tuple(
            spec
            for spec in PRIMARY_RELATIONSHIPS[relationship_type].properties
            if spec.name not in {
                divergence.property_name
                for divergence in RELATIONSHIP_DIVERGENCES
                if relationship_type in divergence.applies_to
            }
        ),
    )
    for relationship_type, shape in _RELATIONSHIP_ENDPOINTS.items()
}

def claim_key_properties(relationship_type: str) -> frozenset[str]:
    """The Claim Key of ``relationship_type``: its declared property names.

    A relationship asserts that a claim exists and what identifies it — nothing
    more. Its declared properties, and only those, are what two edges of the same
    type between the same pair must agree on to be the same edge. A `FUNDED` edge
    means something different at six million than at four; two articles naming
    different figures are making different assertions, and the graph holds both
    rather than letting the last one ingested overwrite the first.

    There is no separate identifying-property table to disagree with this one. The
    rule that decides what a relationship declares is the rule that decides edge
    identity: if two different values mean two different claims, the property is
    declared and therefore identifying; if they do not, the property does not belong
    on the edge, and what the article said stays in the Article Chunk it points to.

    Nothing requires an extractor to produce these. The prompt never asks for one,
    and an edge that arrives without them is written and flagged rather than dropped
    — a missing value is recoverable, an invented one is not.
    """

    shape = RELATIONSHIPS.get(relationship_type)
    return shape.property_names if shape is not None else frozenset()


#: Relationships whose Claim Key can be incomplete, because they have one at all.
KEYED_RELATIONSHIPS = frozenset(
    relationship_type
    for relationship_type, shape in RELATIONSHIPS.items()
    if shape.properties
)

DIVERGENCES = NODE_DIVERGENCES + RELATIONSHIP_DIVERGENCES
