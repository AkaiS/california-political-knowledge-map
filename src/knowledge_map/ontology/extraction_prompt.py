"""Render the model-extractable portion of the News Ontology for the prompt."""

from knowledge_map.ontology import news

WRITE_PATH_LABELS = frozenset({"NewsArticle", "Chunk"})


def render_extraction_ontology() -> str:
    """Render ontology facts that the extraction model is responsible for."""
    labels = news.LABELS - WRITE_PATH_LABELS
    relationships = {
        relationship_type: shape
        for relationship_type, shape in news.RELATIONSHIPS.items()
        if shape.source_labels <= labels and shape.target_labels <= labels
    }

    lines = [
        "## Closed ontology",
        "",
        "Use exactly one of these base labels for each entity; never invent another:",
    ]
    lines.extend(f"- `{label}`" for label in sorted(labels))

    lines.extend(["", "### Sub-label rules", ""])
    for label in sorted(news.SUB_LABELS.keys() & labels):
        allowed = ", ".join(f"`{item}`" for item in sorted(news.SUB_LABELS[label]))
        requirement = "exactly one is required" if label in news.REQUIRED_SUB_LABELS else "optional; use one or more when supported"
        lines.append(f"- `{label}`: {requirement}. Allowed sub-labels: {allowed}.")

    lines.extend(["", "### Properties by label", ""])
    for label in sorted(labels):
        properties = ", ".join(f"`{item}`" for item in sorted(news.PROPERTIES[label])) or "none"
        lines.append(f"- `{label}`: {properties}.")

    lines.extend(
        [
            "",
            (
                "Use only the property names listed for that label. Use ISO dates "
                "(`YYYY-MM-DD`) and integers for years. Omit unknown properties; never guess them."
            ),
            "",
            "## Allowed relationships",
            "",
            "Emit only these relationship types and endpoint label combinations:",
        ]
    )
    for relationship_type, shape in sorted(relationships.items()):
        sources = " or ".join(f"`{item}`" for item in sorted(shape.source_labels))
        targets = " or ".join(f"`{item}`" for item in sorted(shape.target_labels))
        lines.append(f"- `{relationship_type}`: {sources} -> {targets}")

    lines.extend(
        [
            "",
            "### Policy Area vocabulary",
            "",
            "A `PolicyArea` must use one of these IDs and its corresponding canonical name:",
        ]
    )
    lines.extend(f"- `{area.id}`: {area.name}" for area in news.POLICY_AREAS)
    return "\n".join(lines)
