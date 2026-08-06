"""Assertions relating the News Ontology to the primary ontology."""

from . import news, primary


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
        assert news_shape.source_labels == {shortcut.source_label}
        assert news_shape.target_labels == {shortcut.target_label}
        assert shortcut.skips in primary.LABELS

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

        assert shortcut.path[0][0] == shortcut.source_label
        assert shortcut.path[-1][2] == shortcut.target_label
        assert shortcut.skips in {step[2] for step in shortcut.path[:-1]}

    unused_shortcuts = shortcuts.keys() - news.RELATIONSHIPS.keys()
    assert not unused_shortcuts, f"Shortcuts produce undeclared relationships: {sorted(unused_shortcuts)}"
