from knowledge_map.ontology import assert_news_ontology_conforms, news, primary
from knowledge_map.ontology.primary import RelationshipShape
from knowledge_map.ontology.render import GENERATED_PATH, render_news_ontology


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
