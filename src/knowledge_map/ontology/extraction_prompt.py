"""Render the model-extractable portion of the News Ontology for the prompt."""

from knowledge_map.ontology import news, primary


def _relationship_property_lines(relationships: dict) -> list[str]:
    """Fix the form of declared properties, without asking for any of them.

    The lines it renders say how to write a value.  The write path flags a
    missing Claim Key property; an invented one it cannot catch.
    """

    described = {
        relationship_type: primary.RELATIONSHIPS[relationship_type].properties
        for relationship_type in sorted(relationships)
        if primary.RELATIONSHIPS[relationship_type].properties
    }
    if not described:
        return []

    lines = [
        "",
        "### Relationship properties",
        "",
        "Attach any property the text supports. None are required. The properties below "
        "have a fixed form: when you do supply one, write it exactly this way, so the "
        "same value reported by two articles is recognisably the same value.",
        "",
    ]
    for relationship_type, specs in described.items():
        lines.append(f"- `{relationship_type}`:")
        for spec in specs:
            lines.append(f"  - `{spec.name}`: {spec.form}. Example: `{spec.example}`.")

    lines.extend(
        [
            "",
            "Write a value only where the article states one. Never estimate, round, "
            "convert, or carry a value over from elsewhere in the text. An omitted value "
            "is recorded as unknown; an invented one is recorded as fact.",
        ]
    )
    return lines


def render_extraction_ontology() -> str:
    """Render ontology facts that the extraction model is responsible for."""
    labels = news.EXTRACTED_LABELS
    relationships = news.EXTRACTED_RELATIONSHIPS

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

    lines.extend(_relationship_property_lines(relationships))
    return "\n".join(lines)
