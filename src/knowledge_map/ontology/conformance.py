"""Assertions relating the News Ontology to the primary ontology."""

from . import news, primary
from .divergence import assert_divergences_are_unresolved_gaps


def assert_news_ontology_conforms() -> None:
    """Raise ``AssertionError`` with actionable details on ontology drift."""

    unknown_labels = news.LABELS - primary.LABELS
    assert not unknown_labels, f"News Ontology has unknown labels: {sorted(unknown_labels)}"

    shortcuts = {shortcut.relationship_type: shortcut for shortcut in news.SHORTCUTS}
    assert len(shortcuts) == len(news.SHORTCUTS), "Shortcut relationship types must be unique"

    for relationship_type, news_shape in news.RELATIONSHIPS.items():
        endpoint_labels = news_shape.source_labels | news_shape.target_labels
        assert endpoint_labels <= news.LABELS, (
            f"News relationship {relationship_type} uses undeclared labels: "
            f"{sorted(endpoint_labels - news.LABELS)}"
        )
        primary_shape = primary.RELATIONSHIPS.get(relationship_type)
        if (
            primary_shape is not None
            and news_shape.source_labels <= primary_shape.source_labels
            and news_shape.target_labels <= primary_shape.target_labels
        ):
            continue

        shortcut = shortcuts.get(relationship_type)
        assert shortcut is not None, (
            f"News relationship {relationship_type} does not match its primary endpoints "
            "and has no shortcut"
        )
        assert news_shape.source_labels == {shortcut.source_label}, (
            f"Shortcut {relationship_type} starts at {sorted(news_shape.source_labels)}, "
            f"but the edge it produces starts at {shortcut.source_label}"
        )
        assert news_shape.target_labels == {shortcut.target_label}, (
            f"Shortcut {relationship_type} ends at {sorted(news_shape.target_labels)}, "
            f"but the edge it produces ends at {shortcut.target_label}"
        )
        assert shortcut.skips in primary.LABELS, (
            f"Shortcut {relationship_type} skips {shortcut.skips}, which the primary "
            "ontology does not declare"
        )
        assert shortcut.skips not in news.LABELS, (
            f"Shortcut {relationship_type} skips {shortcut.skips}, which the News "
            "Ontology also declares. A shortcut exists because news cannot produce "
            "the node it collapses; declaring the label leaves two ways to say the "
            "same thing, and only one of them is reachable."
        )

        previous_target: str | None = None
        for source, path_relationship, target in shortcut.path:
            assert previous_target is None or source == previous_target, (
                f"Shortcut {relationship_type} has a disconnected path"
            )
            path_shape = primary.RELATIONSHIPS.get(path_relationship)
            assert path_shape is not None, (
                f"Shortcut {relationship_type} uses unknown relationship {path_relationship}"
            )
            assert source in path_shape.source_labels and target in path_shape.target_labels, (
                f"Shortcut {relationship_type} path step "
                f"{source} -{path_relationship}-> {target} is absent from the primary ontology"
            )
            previous_target = target

        assert shortcut.path[0][0] == shortcut.source_label, (
            f"Shortcut {relationship_type} produces an edge from {shortcut.source_label}, "
            f"but its path starts at {shortcut.path[0][0]}"
        )
        assert shortcut.path[-1][2] == shortcut.target_label, (
            f"Shortcut {relationship_type} produces an edge to {shortcut.target_label}, "
            f"but its path ends at {shortcut.path[-1][2]}"
        )
        assert shortcut.skips in {step[2] for step in shortcut.path[:-1]}, (
            f"Shortcut {relationship_type} says it skips {shortcut.skips}, which its own "
            "path never passes through. The path is the whole record of the collapse, so "
            "an edge claiming to skip a node absent from it cannot be expanded back out."
        )

    unused_shortcuts = shortcuts.keys() - news.RELATIONSHIPS.keys()
    assert not unused_shortcuts, f"Shortcuts produce undeclared relationships: {sorted(unused_shortcuts)}"

    assert shortcuts == news.SHORTCUTS_BY_TYPE, "SHORTCUTS_BY_TYPE must index every shortcut"

    assert_divergences_are_unresolved_gaps(news.NODE_DIVERGENCES, news.LABELS)
    assert_divergences_are_unresolved_gaps(
        news.RELATIONSHIP_DIVERGENCES, frozenset(news.RELATIONSHIPS)
    )

    for divergence in news.NODE_DIVERGENCES:
        for label in divergence.applies_to:
            assert divergence.property_name not in news.PROPERTIES[label], (
                f"{label}.{divergence.property_name} is declared a gap and also "
                "declared as a property news supplies. `PROPERTIES` subtracts every "
                "divergence, so this means the label's properties were hand-written "
                "instead of derived."
            )

    for divergence in news.RELATIONSHIP_DIVERGENCES:
        for relationship_type in divergence.applies_to:
            assert divergence.property_name not in news.RELATIONSHIPS[
                relationship_type
            ].property_names, (
                f"{relationship_type}.{divergence.property_name} is declared a gap and "
                "also sits in the Claim Key. A relationship's declared properties are "
                "its Claim Key, so a property news cannot supply would key every edge "
                "on a value no article fills; `RELATIONSHIPS` subtracts every "
                "divergence, so this means the properties were hand-written instead of "
                "derived."
            )

    _assert_every_claim_key_property_has_a_shape()

    declared = {divergence.property_name for divergence in news.DIVERGENCES}
    assert "skips" not in declared, (
        "`skips` is derivable from SHORTCUTS, which holds the path it flattened. "
        "It is a recorded collapse, not an unresolved gap — do not declare it here."
    )


def _assert_every_claim_key_property_has_a_shape() -> None:
    """A relationship's declared properties are its Claim Key, so each needs a shape."""

    for relationship_type, news_shape in news.RELATIONSHIPS.items():
        primary_shape = primary.RELATIONSHIPS[relationship_type]
        unshaped = news_shape.property_names - primary_shape.property_names
        assert not unshaped, (
            f"{relationship_type} is keyed on properties the primary ontology does not "
            f"shape: {sorted(unshaped)}. Declare them on its primary RelationshipShape "
            "first."
        )
        dropped = primary_shape.property_names - news_shape.property_names
        undeclared = dropped - {
            divergence.property_name
            for divergence in news.RELATIONSHIP_DIVERGENCES
            if relationship_type in divergence.applies_to
        }
        assert not undeclared, (
            f"{relationship_type} drops primary properties nothing declares a gap for: "
            f"{sorted(undeclared)}. News relationship properties are inherited, so a "
            "property leaves the Claim Key only by being declared a divergence — "
            "silently narrowing it here would drop the reason along with the property."
        )
        assert news_shape.properties == tuple(
            spec for spec in primary_shape.properties if spec.name in news_shape.property_names
        ), (
            f"{relationship_type} restates its property shapes instead of inheriting "
            "them. The shapes must be the primary ontology's own, or two articles' "
            "claims stop being comparable in the way the Claim Key assumes."
        )
