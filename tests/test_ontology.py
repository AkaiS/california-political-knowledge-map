from pathlib import Path

from knowledge_map.adapters import neo4j_db
from knowledge_map.ontology import (
    assert_news_ontology_conforms,
    conform_extraction_result,
    keys,
    news,
    primary,
)
from knowledge_map.ontology.divergence import Divergence
from knowledge_map.ontology.extraction_prompt import render_extraction_ontology
from knowledge_map.ontology.primary import RelationshipShape
from knowledge_map.ontology.render import GENERATED_PATH, render_news_ontology
from knowledge_map.schemas import ExtractionResult, Node, Relationship


def test_news_ontology_conforms_to_primary_ontology():
    assert_news_ontology_conforms()


def test_news_ontology_excludes_unreachable_and_structured_source_concepts():
    assert not {"LegislativeTenure", "District", "RedistrictingCycle", "ExternalIdentifier"} & news.LABELS
    assert not {
        "HELD_TENURE", "REPRESENTS_DISTRICT", "TRANSITIONED_BY", "EVOLVED_INTO", "HAS_IDENTIFIER"
    } & news.RELATIONSHIPS.keys()


def test_news_ontology_declares_six_tenure_shortcuts():
    assert {shortcut.relationship_type for shortcut in news.SHORTCUTS} == {
        "VOTED_AYE", "VOTED_NO", "ABSTAINED", "SERVES_ON", "CHAIRS", "VICE_CHAIRS"
    }
    assert {shortcut.skips for shortcut in news.SHORTCUTS} == {"LegislativeTenure"}


def test_divergences_cover_every_property_the_write_path_stamps():
    assert news.node_divergence_properties("Bill") == {
        "name", "source_url", "session_verified", "session_inferred", "needs_review",
    }
    assert news.node_divergence_properties("Committee") == {"source_url"}
    assert news.node_divergence_properties("NewsArticle") == set()


def test_only_an_incomplete_claim_key_diverges_on_an_edge():
    # An edge's evidence (`chunks`) and its collapse (`skips`) are not gaps — one is
    # recorded structurally, the other in SHORTCUTS. An unusable key is a real gap,
    # and so is a roll-call position news never reports.
    assert {divergence.property_name for divergence in news.RELATIONSHIP_DIVERGENCES} == {
        "needs_review", "sequence_number",
    }
    assert news.relationship_divergence_properties("FUNDED") == {"needs_review"}
    assert news.relationship_divergence_properties("ENDORSED") == set()


def test_a_vote_event_carries_the_sequence_number_not_the_vote_edge():
    # The value is identical for every voter at one event, so it describes the
    # event's position in the bill's lifecycle, not one legislator's claim.
    assert "sequence_number" in primary.PROPERTIES["LegislativeEvent"]

    for relationship_type in ("VOTED_AYE", "VOTED_NO", "ABSTAINED"):
        assert primary.RELATIONSHIPS[relationship_type].properties == ()
        assert not primary.RELATIONSHIPS[relationship_type].property_names
        assert not news.RELATIONSHIPS[relationship_type].property_names
        # No declared properties means an empty Claim Key, so a news-derived vote
        # edge and a later legislative-derived one merge rather than duplicate.
        assert news.claim_key_properties(relationship_type) == frozenset()


def test_news_supplies_neither_a_roll_call_position_nor_event_discrimination():
    # News declares no `sequence_number` anywhere: not on the event it belongs to,
    # and not on the vote edges that used to carry it.
    assert "sequence_number" not in news.PROPERTIES["LegislativeEvent"]

    divergence = next(
        item
        for item in news.RELATIONSHIP_DIVERGENCES
        if item.property_name == "sequence_number"
    )
    assert divergence.applies_to == {"VOTED_AYE", "VOTED_NO", "ABSTAINED"}
    assert "no roll-call position and no event discrimination" in divergence.reason
    # Event discrimination stays on the sub-label; no claim is made about which
    # events news reports.
    assert "Vote" in news.SUB_LABELS["LegislativeEvent"]


def test_a_relationships_declared_properties_are_its_claim_key():
    # One table decides edge identity. There is no second, identifying-property
    # table that could disagree with what the relationship declares.
    assert not hasattr(news, "IDENTIFYING_PROPERTIES")

    for relationship_type, shape in news.RELATIONSHIPS.items():
        assert news.claim_key_properties(relationship_type) == shape.property_names
        assert shape.property_names <= primary.RELATIONSHIPS[relationship_type].property_names

    assert news.claim_key_properties("FUNDED") == {"amount", "date", "transaction_id"}
    assert news.claim_key_properties("DECLARED_STANCE") == {"alignment"}
    # Endorsement is binary: the edge's existence is the whole claim.
    assert news.claim_key_properties("ENDORSED") == frozenset()


def test_conformance_rejects_a_claim_key_the_ontology_does_not_shape(monkeypatch):
    from knowledge_map.ontology.properties import PropertySpec, normalize_text

    unshaped = dict(news.RELATIONSHIPS)
    unshaped["ENDORSED"] = RelationshipShape(
        source_labels=news.RELATIONSHIPS["ENDORSED"].source_labels,
        target_labels=news.RELATIONSHIPS["ENDORSED"].target_labels,
        properties=(PropertySpec("weight", normalize_text, form="text", example="heavy"),),
    )
    monkeypatch.setattr(news, "RELATIONSHIPS", unshaped)

    try:
        assert_news_ontology_conforms()
    except AssertionError as error:
        assert "weight" in str(error)
    else:
        raise AssertionError("Conformance unexpectedly accepted an unshaped claim key")


def test_a_shortcut_edge_is_reversible_from_its_type_alone():
    shortcut = news.SHORTCUTS_BY_TYPE["VOTED_AYE"]

    assert shortcut.path == (
        ("Politician", "HELD_TENURE", "LegislativeTenure"),
        ("LegislativeTenure", "VOTED_AYE", "LegislativeEvent"),
    )
    assert shortcut.skips == "LegislativeTenure"
    # The flattened path is the whole reversal: nothing else need be recorded.
    assert "skips" not in news.relationship_divergence_properties("VOTED_AYE")


def test_divergent_properties_are_never_model_extractable():
    for label in news.LABELS:
        assert not news.node_divergence_properties(label) & news.PROPERTIES[label], (
            f"{label} declares a property the pipeline also stamps"
        )


def test_every_divergence_states_a_reason_and_applies_somewhere():
    for divergence in news.DIVERGENCES:
        assert divergence.reason.strip()
        assert divergence.applies_to


def test_conformance_rejects_a_recorded_collapse_declared_as_a_divergence(monkeypatch):
    as_divergence = news.RELATIONSHIP_DIVERGENCES + (
        Divergence(
            property_name="skips",
            applies_to=frozenset(news.SHORTCUTS_BY_TYPE),
            reason="derivable from SHORTCUTS",
        ),
    )
    monkeypatch.setattr(news, "RELATIONSHIP_DIVERGENCES", as_divergence)
    monkeypatch.setattr(news, "DIVERGENCES", news.NODE_DIVERGENCES + as_divergence)

    try:
        assert_news_ontology_conforms()
    except AssertionError as error:
        assert "skips" in str(error)
    else:
        raise AssertionError("Conformance unexpectedly accepted a recorded collapse")


def test_conformance_rejects_a_divergence_the_primary_ontology_declares(monkeypatch):
    redundant = news.NODE_DIVERGENCES + (
        Divergence(
            property_name="current_status",
            applies_to=frozenset({"Bill"}),
            reason="already declared",
        ),
    )
    monkeypatch.setattr(news, "NODE_DIVERGENCES", redundant)

    try:
        assert_news_ontology_conforms()
    except AssertionError as error:
        assert "current_status" in str(error)
    else:
        raise AssertionError("Conformance unexpectedly accepted a redundant divergence")


def test_the_prompt_asks_for_a_form_the_write_path_actually_accepts():
    """Every example the prompt shows must survive its own normalizer.

    This is the join between the two halves: the prompt tells the model how to write
    a value, and the write path decides whether it is legible. If they drift, the
    model complies perfectly and every claim still lands flagged.
    """

    for relationship_type, shape in primary.RELATIONSHIPS.items():
        for spec in shape.properties:
            assert spec.normalize(spec.example) is not None, (
                f"{relationship_type}.{spec.name} advertises `{spec.example}` in the "
                "extraction prompt, but its own normalizer rejects it"
            )


def test_the_prompt_fixes_the_form_of_a_property_without_demanding_one():
    section = render_extraction_ontology()

    assert "`alignment`: exactly one of `POSITIVE`, `NEGATIVE`, `NEUTRAL`" in section
    assert "`amount`: a dollar figure" in section
    assert "None are required." in section


def test_the_prompt_never_ranks_a_relationship_property_as_required():
    """Asking for a value the article withheld is an invitation to invent one.

    An absent amount is already handled deterministically — the write path flags the
    edge. A fabricated amount is not: it keys a confident, wrong edge. So the model is
    told how to write a value, never that it owes one.
    """

    section = render_extraction_ontology()

    assert "(required)" not in section
    assert "(optional)" not in section
    assert "Write a value only where the article states one." in section


def test_an_identifying_property_is_a_write_path_concern_not_a_prompt_one():
    # The requirement lives here, where a missing value becomes a flag rather than
    # a demand the model can fail.
    assert news.claim_key_properties("FUNDED") == {"amount", "date", "transaction_id"}
    assert "needs_review" in news.relationship_divergence_properties("FUNDED")


def test_the_stance_enum_cannot_drift_from_what_the_prompt_advertises():
    spec = primary.RELATIONSHIPS["DECLARED_STANCE"].spec("alignment")

    for value in ("POSITIVE", "NEGATIVE", "NEUTRAL"):
        assert f"`{value}`" in spec.form
        assert spec.normalize(value) == value
    assert spec.normalize("SUPPORTIVE") is None


def test_generated_news_ontology_is_current():
    assert GENERATED_PATH.read_text() == render_news_ontology()


def test_conformance_fails_loudly_for_an_unknown_news_label(monkeypatch):
    monkeypatch.setattr(news, "LABELS", news.LABELS | {"UnknownLabel"})

    try:
        assert_news_ontology_conforms()
    except AssertionError as error:
        assert "UnknownLabel" in str(error)
    else:
        raise AssertionError("Conformance unexpectedly accepted an unknown label")


def test_conformance_fails_loudly_for_incompatible_endpoints(monkeypatch):
    incompatible = dict(news.RELATIONSHIPS)
    incompatible["ACTION_ON"] = RelationshipShape(
        source_labels=frozenset({"Politician"}),
        target_labels=frozenset({"Bill"}),
    )
    monkeypatch.setattr(news, "RELATIONSHIPS", incompatible)

    try:
        assert_news_ontology_conforms()
    except AssertionError as error:
        assert "ACTION_ON" in str(error)
    else:
        raise AssertionError("Conformance unexpectedly accepted incompatible endpoints")


def test_conformance_fails_loudly_when_primary_endpoints_drift(monkeypatch):
    changed_primary = dict(primary.RELATIONSHIPS)
    changed_primary["ACTION_ON"] = RelationshipShape(
        source_labels=frozenset({"Politician"}),
        target_labels=frozenset({"Bill"}),
    )
    monkeypatch.setattr(primary, "RELATIONSHIPS", changed_primary)

    try:
        assert_news_ontology_conforms()
    except AssertionError as error:
        assert "ACTION_ON" in str(error)
    else:
        raise AssertionError("Conformance unexpectedly accepted primary-ontology drift")


def test_extraction_conformance_rejects_write_path_labels():
    result = ExtractionResult(
        nodes=[
            Node(name="A California Story", label="NewsArticle"),
            Node(name="A California Story #1", label="Chunk"),
            Node(name="Mystery", label="PoliticalActor"),
            Node(name="Alex Lee", label="Politician"),
        ],
        relationships=[],
    )

    outcome = conform_extraction_result(result, "sha256:abc")

    assert [node.name for node in outcome.result.nodes] == ["Alex Lee"]
    assert [(drop.category, drop.value, drop.chunk_id) for drop in outcome.drops] == [
        ("rejected_labels", "NewsArticle", "sha256:abc"),
        ("rejected_labels", "Chunk", "sha256:abc"),
        ("rejected_labels", "PoliticalActor", "sha256:abc"),
    ]


def test_extraction_conformance_keeps_conforming_entities_beside_a_bad_one():
    result = ExtractionResult(
        nodes=[
            Node(name="A California Story", label="NewsArticle"),
            Node(name="AB 1", label="Bill", properties={"number": "AB 1"}),
            Node(name="Good Vote", label="LegislativeEvent", sub_labels=["Vote"]),
        ],
        relationships=[
            Relationship(source="Good Vote", target="AB 1", relationship_type="ACTION_ON"),
        ],
    )

    outcome = conform_extraction_result(result, "sha256:abc")

    assert [node.name for node in outcome.result.nodes] == ["AB 1", "Good Vote"]
    assert [rel.relationship_type for rel in outcome.result.relationships] == ["ACTION_ON"]
    assert len(outcome.drops) == 1


def test_extraction_conformance_leaves_its_input_untouched():
    result = ExtractionResult(
        nodes=[Node(name="Alex Lee", label="Politician", properties={"nickname": "Al"})],
        relationships=[],
    )

    outcome = conform_extraction_result(result, "sha256:abc")

    assert result.nodes[0].properties == {"nickname": "Al"}
    assert outcome.result.nodes[0].properties == {}


def test_extraction_conformance_drops_undeclared_relationship_properties():
    result = ExtractionResult(
        nodes=[
            Node(name="Big PAC", label="Organization", sub_labels=["PAC"]),
            Node(name="Yes on 12", label="Campaign", sub_labels=["BallotMeasureCampaign"]),
        ],
        relationships=[
            Relationship(
                source="Big PAC",
                target="Yes on 12",
                relationship_type="FUNDED",
                properties={"amount": "$6 million", "mood": "enthusiastic"},
            ),
        ],
    )

    outcome = conform_extraction_result(result, "sha256:abc")

    # The declared property is untouched; the invented one never reaches the edge.
    assert [rel.properties for rel in outcome.result.relationships] == [{"amount": "$6 million"}]
    assert [(drop.category, drop.value, drop.chunk_id) for drop in outcome.drops] == [
        ("rejected_relationship_property_names", "mood", "sha256:abc"),
    ]
    assert result.relationships[0].properties == {"amount": "$6 million", "mood": "enthusiastic"}


def test_a_relationship_survives_losing_every_property_it_carried():
    # Losing an edge's detail costs it its nuance, never its existence: the claim
    # was still asserted, and the Article Chunk still holds what the article said.
    result = ExtractionResult(
        nodes=[
            Node(name="Alex Lee", label="Politician"),
            Node(name="Budget Committee", label="Committee"),
        ],
        relationships=[
            Relationship(
                source="Alex Lee",
                target="Budget Committee",
                relationship_type="SERVES_ON",
                properties={"since": "2000", "role": "member"},
            ),
        ],
    )

    outcome = conform_extraction_result(result, "sha256:abc")

    assert [rel.relationship_type for rel in outcome.result.relationships] == ["SERVES_ON"]
    assert outcome.result.relationships[0].properties == {}
    assert {drop.value for drop in outcome.drops} == {"since", "role"}


def test_a_dropped_relationship_property_is_recorded_apart_from_a_node_property():
    result = ExtractionResult(
        nodes=[
            Node(name="Alex Lee", label="Politician", properties={"nickname": "Al"}),
            Node(name="Budget Committee", label="Committee"),
        ],
        relationships=[
            Relationship(
                source="Alex Lee",
                target="Budget Committee",
                relationship_type="SERVES_ON",
                properties={"nickname": "Al"},
            ),
        ],
    )

    outcome = conform_extraction_result(result, "sha256:abc")

    # Same property name on both sides of the edge, two different categories: a model
    # inventing node fields is a different defect from one attaching payload to edges.
    assert [(drop.category, drop.value) for drop in outcome.drops] == [
        ("rejected_property_names", "nickname"),
        ("rejected_relationship_property_names", "nickname"),
    ]


def test_a_news_relationship_declares_the_properties_the_prompt_asks_for():
    # Conformance and the extraction prompt read one table, so the prompt can never
    # ask for a property conformance would then drop.
    for relationship_type, shape in news.RELATIONSHIPS.items():
        assert shape.properties == primary.RELATIONSHIPS[relationship_type].properties

    assert news.RELATIONSHIPS["FUNDED"].property_names == {"amount", "date", "transaction_id"}
    assert news.RELATIONSHIPS["ENDORSED"].property_names == frozenset()


def test_write_path_labels_are_excluded_from_the_extracted_subset():
    assert news.WRITE_PATH_LABELS == {"NewsArticle", "Chunk"}
    assert news.EXTRACTED_LABELS == news.LABELS - news.WRITE_PATH_LABELS


def test_the_general_key_is_the_label_and_the_slugged_name():
    assert keys.derived_key("Politician", "Alex Lee") == "Politician:alex-lee"
    assert keys.derived_key("PolicyArea", "Housing & Land Use") == "PolicyArea:housing-land-use"
    assert keys.derived_key("Organization", "Café Móvil") == "Organization:cafe-movil"


def test_a_bill_key_is_qualified_by_its_session():
    assert keys.bill_key("2025-2026", "AB 218", "Assembly Bill 218") == "Bill:2025-2026:ab-218"
    assert keys.bill_key("2019-2020", "AB 218", "Assembly Bill 218") == "Bill:2019-2020:ab-218"


def test_an_unresolved_session_still_mints_a_stable_bill_key():
    assert keys.bill_key(None, "AB 218", "Assembly Bill 218") == "Bill:unresolved:ab-218"
    assert keys.bill_key(None, None, "the housing bill") == "Bill:unresolved:the-housing-bill"


def test_the_write_path_mints_its_keys_through_the_shared_contract():
    """Both Bill key call sites are the imported function, not a re-derivation."""

    source = Path(neo4j_db.__file__).read_text()

    assert "from knowledge_map.ontology.keys import bill_key, derived_key" in source
    assert source.count("bill_key(") == 2
    assert '"Bill:' not in source and "'Bill:" not in source
