import re
from dataclasses import replace
from pathlib import Path

import pytest
from pydantic import ValidationError

from knowledge_map.ontology import (
    assert_news_ontology_conforms,
    conform_extraction_result,
    keys,
    news,
    primary,
)
from knowledge_map.ontology.divergence import (
    NOT_SUPPLIED,
    STAMPED,
    Divergence,
    gap_directions,
)
from knowledge_map.ontology.extraction_conformance import ConformanceDrop
from knowledge_map.ontology.extraction_prompt import render_extraction_ontology
from knowledge_map.ontology.primary import RelationshipShape
from knowledge_map.ontology.render import GENERATED_PATH, render_news_ontology
from knowledge_map.schemas import DropCategory, ExtractionResult, Node, Relationship


def _conformance_error(accepted: str) -> str:
    """The message conformance failed with, or a failure saying it did not fail.

    Every rule below is stated as what conformance *rejects*, so this runs it against
    a deliberately broken ontology and hands back what it complained about. A rule
    that has silently stopped firing shows up here as an unexpected acceptance rather
    than as a passing test.
    """

    try:
        assert_news_ontology_conforms()
    except AssertionError as error:
        return str(error)
    raise AssertionError(f"Conformance unexpectedly accepted {accepted}")


def _break_shortcut(monkeypatch, relationship_type: str, **changes) -> None:
    """Replace one shortcut rule, keeping the two shortcut tables in step."""

    shortcuts = tuple(
        replace(shortcut, **changes)
        if shortcut.relationship_type == relationship_type
        else shortcut
        for shortcut in news.SHORTCUTS
    )
    monkeypatch.setattr(news, "SHORTCUTS", shortcuts)
    monkeypatch.setattr(
        news,
        "SHORTCUTS_BY_TYPE",
        {shortcut.relationship_type: shortcut for shortcut in shortcuts},
    )


def test_news_ontology_conforms_to_primary_ontology():
    assert_news_ontology_conforms()


# --- Shortcuts: a collapsed path that stays reversible -----------------------------


def test_conformance_rejects_a_shortcut_whose_path_step_the_primary_ontology_lacks(monkeypatch):
    # The path is the whole record of the collapse. A step the primary ontology never
    # declared cannot be expanded back out, so the edge is a dead end.
    _break_shortcut(
        monkeypatch,
        "VOTED_AYE",
        path=(
            ("Politician", "HELD_TENURE", "LegislativeTenure"),
            ("LegislativeTenure", "VOTED_AYE", "Prop"),
        ),
    )

    assert "VOTED_AYE" in _conformance_error("a path step absent from the primary ontology")


def test_conformance_rejects_a_shortcut_whose_path_does_not_join_up(monkeypatch):
    _break_shortcut(
        monkeypatch,
        "VOTED_AYE",
        path=(
            ("Politician", "HELD_TENURE", "LegislativeTenure"),
            ("Committee", "VOTED_AYE", "LegislativeEvent"),
        ),
    )

    assert "disconnected" in _conformance_error("a path with a gap in the middle")


def test_conformance_rejects_a_shortcut_that_skips_a_node_off_its_own_path(monkeypatch):
    _break_shortcut(monkeypatch, "VOTED_AYE", skips="District")

    assert "District" in _conformance_error("a collapse the path never made")


def test_conformance_rejects_a_shortcut_for_a_label_news_already_declares(monkeypatch):
    # A shortcut exists because news cannot produce the node it collapses. Declare the
    # label as well and the ontology offers two routes, only one of them reachable.
    monkeypatch.setattr(news, "LABELS", news.LABELS | {"LegislativeTenure"})

    assert "LegislativeTenure" in _conformance_error("a shortcut around a declared label")


def test_conformance_rejects_two_shortcuts_producing_the_same_edge(monkeypatch):
    monkeypatch.setattr(news, "SHORTCUTS", news.SHORTCUTS + (news.SHORTCUTS[0],))

    assert "unique" in _conformance_error("a duplicated shortcut")


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

    assert "skips" in _conformance_error("a recorded collapse")


# --- Divergences: a declared gap that actually takes effect ------------------------


def test_conformance_rejects_a_divergence_applying_outside_the_news_ontology(monkeypatch):
    off_ontology = news.NODE_DIVERGENCES + (
        Divergence(
            property_name="district_number",
            applies_to=frozenset({"District"}),
            reason="news does not declare this label at all",
        ),
    )
    monkeypatch.setattr(news, "NODE_DIVERGENCES", off_ontology)

    assert "District" in _conformance_error("an off-ontology divergence")


def test_conformance_rejects_a_divergence_that_states_no_reason(monkeypatch):
    # The reason is the whole content of a gap: it says what nothing we hold can
    # settle. A blank one records that something is missing and not what.
    unexplained = news.NODE_DIVERGENCES + (
        Divergence(property_name="fppc_id", applies_to=frozenset({"Organization"}), reason="  "),
    )
    monkeypatch.setattr(news, "NODE_DIVERGENCES", unexplained)

    assert "fppc_id" in _conformance_error("a divergence with no reason")


def test_conformance_rejects_a_divergence_that_applies_to_nothing(monkeypatch):
    applies_nowhere = news.NODE_DIVERGENCES + (
        Divergence(property_name="fppc_id", applies_to=frozenset(), reason="no filing was named"),
    )
    monkeypatch.setattr(news, "NODE_DIVERGENCES", applies_nowhere)

    assert "fppc_id" in _conformance_error("a divergence applying to nothing")


def test_conformance_rejects_properties_that_were_hand_written_past_a_divergence(monkeypatch):
    # The subtraction in `PROPERTIES` is what makes a declared gap real. Restore the
    # property by hand and the ontology claims news both supplies it and cannot.
    hand_written = dict(news.PROPERTIES)
    hand_written["LegislativeEvent"] = primary.PROPERTIES["LegislativeEvent"]
    monkeypatch.setattr(news, "PROPERTIES", hand_written)

    assert "sequence_number" in _conformance_error("a hand-written property set")


def test_a_declared_gap_removes_the_property_from_what_the_model_is_asked_for():
    """Declaring a gap has to change the prompt, or it is just a note in a table.

    The extraction prompt is built from `news.PROPERTIES`, which subtracts every
    divergence. So a property news cannot supply is never advertised to the model,
    and a property the write path stamps is never one the model is invited to guess.
    """

    lines = render_extraction_ontology().splitlines()

    for divergence in news.NODE_DIVERGENCES:
        for label in divergence.applies_to & news.EXTRACTED_LABELS:
            advertised = [line for line in lines if line.startswith(f"- `{label}`: ")]
            assert advertised, f"The prompt lists no properties for {label}"
            assert all(f"`{divergence.property_name}`" not in line for line in advertised), (
                f"{label}.{divergence.property_name} is declared a gap and still asked for"
            )


def test_the_direction_of_a_gap_is_read_off_the_primary_ontology():
    # Nothing on a Divergence says which way it parts, because the primary ontology
    # already answers it: declared there means news drops it, absent means the write
    # path stamps it.
    dropped = next(
        item for item in news.NODE_DIVERGENCES if item.property_name == "sequence_number"
    )
    stamped = next(
        item for item in news.NODE_DIVERGENCES if item.property_name == "session_verified"
    )

    assert gap_directions(dropped, primary.PROPERTIES) == (NOT_SUPPLIED,)
    assert gap_directions(stamped, primary.PROPERTIES) == (STAMPED,)


def test_a_divergence_reports_both_directions_when_its_items_differ():
    # `applies_to` is a set, and nothing makes its items agree on direction. A
    # single stored field would have to pick one and be wrong for the rest.
    mixed = Divergence(
        property_name="current_status",
        applies_to=frozenset({"Bill", "LegislativeEvent"}),
        reason="declared for one label, stamped for the other",
    )

    assert "current_status" in primary.PROPERTIES["Bill"]
    assert "current_status" not in primary.PROPERTIES["LegislativeEvent"]
    assert gap_directions(mixed, primary.PROPERTIES) == tuple(
        sorted({NOT_SUPPLIED, STAMPED})
    )


# --- Labels and relationships -------------------------------------------------------


def test_conformance_fails_loudly_for_an_unknown_news_label(monkeypatch):
    monkeypatch.setattr(news, "LABELS", news.LABELS | {"UnknownLabel"})

    assert "UnknownLabel" in _conformance_error("an unknown label")


def test_conformance_fails_loudly_for_incompatible_endpoints(monkeypatch):
    incompatible = dict(news.RELATIONSHIPS)
    incompatible["ACTION_ON"] = RelationshipShape(
        source_labels=frozenset({"Politician"}),
        target_labels=frozenset({"Bill"}),
    )
    monkeypatch.setattr(news, "RELATIONSHIPS", incompatible)

    assert "ACTION_ON" in _conformance_error("incompatible endpoints")


def test_conformance_fails_loudly_when_primary_endpoints_drift(monkeypatch):
    changed_primary = dict(primary.RELATIONSHIPS)
    changed_primary["ACTION_ON"] = RelationshipShape(
        source_labels=frozenset({"Politician"}),
        target_labels=frozenset({"Bill"}),
    )
    monkeypatch.setattr(primary, "RELATIONSHIPS", changed_primary)

    assert "ACTION_ON" in _conformance_error("primary-ontology drift")


def test_conformance_rejects_a_claim_key_the_ontology_does_not_shape(monkeypatch):
    # A relationship's declared properties are its Claim Key. Keying on a property
    # the primary ontology does not shape means keying on whatever string the model
    # happened to emit, which fragments the graph instead of aligning it.
    from knowledge_map.ontology.properties import PropertySpec, normalize_text

    unshaped = dict(news.RELATIONSHIPS)
    unshaped["ENDORSED"] = RelationshipShape(
        source_labels=news.RELATIONSHIPS["ENDORSED"].source_labels,
        target_labels=news.RELATIONSHIPS["ENDORSED"].target_labels,
        properties=(PropertySpec("weight", normalize_text, form="text", example="heavy"),),
    )
    monkeypatch.setattr(news, "RELATIONSHIPS", unshaped)

    assert "weight" in _conformance_error("an unshaped claim key")


def test_a_relationship_property_news_cannot_supply_leaves_the_claim_key():
    # `transaction_id` is an FPPC filing id. Prose never carries one, so keying on it
    # would put a value in every funding edge's key that no article can fill.
    assert "transaction_id" in primary.RELATIONSHIPS["FUNDED"].property_names
    assert "transaction_id" not in news.RELATIONSHIPS["FUNDED"].property_names
    assert news.claim_key_properties("FUNDED") == frozenset({"amount", "date"})


def test_a_diverged_relationship_property_still_leaves_the_relationship_keyed():
    # Subtracting one property is not the same as declaring the edge unkeyed: two
    # articles naming different amounts still assert different claims.
    assert "FUNDED" in news.KEYED_RELATIONSHIPS


def test_conformance_rejects_a_claim_key_narrowed_without_a_declared_gap(monkeypatch):
    # A property leaves the Claim Key by being declared a gap, never by being quietly
    # dropped — otherwise the reason it left goes unrecorded.
    narrowed = dict(news.RELATIONSHIPS)
    narrowed["DECLARED_STANCE"] = RelationshipShape(
        source_labels=news.RELATIONSHIPS["DECLARED_STANCE"].source_labels,
        target_labels=news.RELATIONSHIPS["DECLARED_STANCE"].target_labels,
        properties=(),
    )
    monkeypatch.setattr(news, "RELATIONSHIPS", narrowed)

    assert "alignment" in _conformance_error("a silently narrowed claim key")


def test_conformance_rejects_a_claim_key_hand_written_past_a_relationship_divergence(monkeypatch):
    # The mirror of the node check: restoring a diverged property by hand makes the
    # ontology claim news both supplies it and cannot.
    hand_written = dict(news.RELATIONSHIPS)
    hand_written["FUNDED"] = RelationshipShape(
        source_labels=news.RELATIONSHIPS["FUNDED"].source_labels,
        target_labels=news.RELATIONSHIPS["FUNDED"].target_labels,
        properties=primary.RELATIONSHIPS["FUNDED"].properties,
    )
    monkeypatch.setattr(news, "RELATIONSHIPS", hand_written)

    assert "transaction_id" in _conformance_error("a hand-written claim key")


# --- The extraction prompt ----------------------------------------------------------


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


def test_the_prompt_fixes_the_form_of_every_property_it_will_accept():
    """A property the prompt names without a form is one the model can write any way.

    Conformance keeps whatever the model attached to a declared property, so an
    unadvertised form is how two articles reporting the same figure end up keying
    two different edges.
    """

    section = render_extraction_ontology()

    for relationship_type, shape in news.RELATIONSHIPS.items():
        if not shape.source_labels <= news.EXTRACTED_LABELS:
            continue
        if not shape.target_labels <= news.EXTRACTED_LABELS:
            continue
        for spec in shape.properties:
            assert f"`{spec.name}`: {spec.form}" in section, (
                f"{relationship_type}.{spec.name} is asked for without stating its form"
            )
            assert f"`{spec.example}`" in section


def test_the_prompt_never_ranks_a_relationship_property_as_required():
    """Asking for a value the article withheld is an invitation to invent one.

    An absent amount is already handled deterministically — the write path flags the
    edge. A fabricated amount is not: it keys a confident, wrong edge. So the model is
    told how to write a value, never that it owes one.
    """

    section = render_extraction_ontology()

    assert "(required)" not in section
    assert "(optional)" not in section
    assert "None are required." in section
    assert "Write a value only where the article states one." in section


def test_the_prompt_never_asks_the_model_for_a_label_the_write_path_owns():
    # An article and its chunks are written from the article itself. Listing them as
    # extractable invites output that conformance would only drop again.
    section = render_extraction_ontology()

    for label in news.WRITE_PATH_LABELS:
        assert f"- `{label}`" not in section


def test_the_stance_enum_cannot_drift_from_what_the_prompt_advertises():
    spec = primary.RELATIONSHIPS["DECLARED_STANCE"].spec("alignment")

    for value in ("POSITIVE", "NEGATIVE", "NEUTRAL"):
        assert f"`{value}`" in spec.form
        assert spec.normalize(value) == value
    assert spec.normalize("SUPPORTIVE") is None


def test_generated_news_ontology_is_current():
    assert GENERATED_PATH.read_text() == render_news_ontology()


# --- Extraction conformance ---------------------------------------------------------


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


def test_a_drop_cannot_invent_an_adherence_report_category():
    # The categories are closed: a drop recorded under a name nobody reads is a
    # construction-time failure, not a fifth bucket.
    with pytest.raises(ValidationError):
        ConformanceDrop(
            category="rejected_vibes", value="Club", chunk_id="sha256:abc", reason="typo"
        )


def test_every_conformance_drop_lands_in_a_declared_category():
    result = ExtractionResult(
        nodes=[
            Node(name="A California Story", label="NewsArticle"),
            Node(name="Alex Lee", label="Politician", properties={"nickname": "Al"}),
            Node(name="Budget Committee", label="Committee"),
        ],
        relationships=[
            Relationship(source="Alex Lee", target="Budget Committee",
                         relationship_type="SERVES_ON", properties={"nickname": "Al"}),
            Relationship(source="Alex Lee", target="Budget Committee",
                         relationship_type="KNOWS"),
        ],
    )

    outcome = conform_extraction_result(result, "sha256:abc")

    assert {drop.category for drop in outcome.drops} == set(DropCategory)


# --- Keys ---------------------------------------------------------------------------


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


# --- The primary ontology is authored in `ontology.md`; `primary.py` mirrors it. ---
#
# The mirror is hand-copied, so nothing but a parse of the document can tell us the
# two still agree. These helpers read the document's structure — headings, property
# bullets, table rows — and never restate what it says, so editing either artifact
# alone fails loudly.

PRIMARY_ONTOLOGY_PATH = Path(__file__).resolve().parents[1] / "ontology.md"

_LABEL_HEADING = re.compile(r"^#{2,6}\s+`:(\w+)`\s*$")
_SECTION_HEADING = re.compile(r"^##\s+\S")
_PROPERTY_BULLET = re.compile(r"^\s*-\s+`(\w+)`:\s+`")
_SUB_LABEL_BULLET = re.compile(r"^\s*-\s+`:")
_LABEL_TOKEN = re.compile(r"`:(\w+)`")
_PROPERTY_TOKEN = re.compile(r"`(\w+):\s*[\w<>]+`")
_NONE_CELL = re.compile(r"^[_*\s]*None[_*\s]*$")
_ANY_CORE_ENTITY = re.compile(r"any\s+(?:resolvable\s+)?core\s+entity", re.IGNORECASE)
_TABLE_DIVIDER = re.compile(r"^[\s:|-]+$")


def _document_lines() -> list[str]:
    return PRIMARY_ONTOLOGY_PATH.read_text().splitlines()


def _parse_document_nodes() -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """Return each documented label's property names and its sub-labels."""

    properties: dict[str, set[str]] = {}
    sub_labels: dict[str, set[str]] = {}
    label: str | None = None

    for line in _document_lines():
        heading = _LABEL_HEADING.match(line)
        if heading:
            label = heading.group(1)
            properties[label] = set()
            continue
        if label is None:
            continue
        if _SECTION_HEADING.match(line):
            label = None
            continue

        bullet = _PROPERTY_BULLET.match(line)
        if bullet:
            properties[label].add(bullet.group(1))
        elif _SUB_LABEL_BULLET.match(line):
            sub_labels.setdefault(label, set()).update(_LABEL_TOKEN.findall(line))

    return properties, sub_labels


def _parse_endpoint_cell(cell: str, core_entity_labels: frozenset[str]) -> set[str]:
    labels = set(_LABEL_TOKEN.findall(cell))
    if labels:
        return labels
    if _ANY_CORE_ENTITY.search(cell):
        return set(core_entity_labels)
    raise AssertionError(f"Unparsed endpoint cell in ontology.md: {cell!r}")


def _parse_property_cell(cell: str) -> set[str]:
    names = set(_PROPERTY_TOKEN.findall(cell))
    if names:
        return names
    if _NONE_CELL.match(cell):
        return set()
    raise AssertionError(f"Unparsed property cell in ontology.md: {cell!r}")


def _parse_document_relationships(
    core_entity_labels: frozenset[str],
) -> dict[str, tuple[set[str], set[str], set[str]]]:
    """Return each documented relationship type's sources, targets and properties.

    A type documented on several rows — one per source label — is the union of them.
    """

    relationships: dict[str, tuple[set[str], set[str], set[str]]] = {}

    for line in _document_lines():
        row = line.strip()
        if not row.startswith("|"):
            continue
        cells = [cell.strip() for cell in re.split(r"(?<!\\)\|", row.strip("|"))]
        if len(cells) < 5 or _TABLE_DIVIDER.match(row) or cells[1].startswith("**"):
            continue

        relationship_type = cells[1].strip("`")
        sources = _parse_endpoint_cell(cells[0], core_entity_labels)
        targets = _parse_endpoint_cell(cells[2], core_entity_labels)
        properties = _parse_property_cell(cells[3])

        if relationship_type in relationships:
            known_sources, known_targets, known_properties = relationships[relationship_type]
            assert known_properties == properties, (
                f"{relationship_type} is documented twice with different properties"
            )
            relationships[relationship_type] = (
                known_sources | sources, known_targets | targets, known_properties
            )
        else:
            relationships[relationship_type] = (sources, targets, properties)

    return relationships


def test_the_primary_ontology_module_mirrors_the_documents_labels_and_properties():
    documented_properties, _ = _parse_document_nodes()

    assert documented_properties, "Parsed no labels out of ontology.md"
    assert set(documented_properties) == set(primary.LABELS)
    assert documented_properties == {
        label: set(names) for label, names in primary.PROPERTIES.items()
    }


def test_the_primary_ontology_module_mirrors_the_documents_sub_labels():
    _, documented_sub_labels = _parse_document_nodes()

    assert documented_sub_labels == {
        label: set(names) for label, names in primary.SUB_LABELS.items()
    }


def test_the_primary_ontology_module_mirrors_the_documents_relationship_table():
    documented = _parse_document_relationships(primary.CORE_ENTITY_LABELS)

    assert documented, "Parsed no relationships out of ontology.md"
    assert set(documented) == set(primary.RELATIONSHIPS)

    for relationship_type, (sources, targets, properties) in documented.items():
        shape = primary.RELATIONSHIPS[relationship_type]
        assert sources == set(shape.source_labels), relationship_type
        assert targets == set(shape.target_labels), relationship_type
        assert properties == set(shape.property_names), relationship_type
