"""Render the model-extractable portion of the News Ontology for the prompt."""

from knowledge_map.ontology import news, primary
from knowledge_map.prompts import load_prompt


def _relationship_property_lines(relationships: dict) -> list[str]:
    """Fix the form of declared properties, and ask only for the entailed ones.

    The lines it renders say how to write a value.  The write path flags a
    missing Claim Key property; an invented one it cannot catch, which is why
    a property the article can withhold is never asked for.  An entailed
    property is the exception the asymmetry does not reach: the passage that
    states the claim has already stated the value, so requesting it invites
    nothing.
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
        load_prompt("extraction/relationship-properties-heading", version=1),
        "",
        load_prompt("extraction/relationship-properties-instructions", version=1),
        "",
    ]
    for relationship_type, specs in described.items():
        lines.append(
            load_prompt("extraction/relationship-heading", version=1).format(
                relationship_type=relationship_type
            )
        )
        for spec in specs:
            entailed = (
                load_prompt("extraction/entailed-property-instructions", version=1)
                if spec.entailed
                else ""
            )
            lines.append(
                load_prompt("extraction/relationship-property", version=1).format(
                    name=spec.name, form=spec.form, example=spec.example, entailed=entailed
                )
            )

    lines.extend(
        [
            "",
            load_prompt("extraction/unknown-property-instructions", version=1),
        ]
    )
    return lines


def render_extraction_ontology() -> str:
    """Render ontology facts that the extraction model is responsible for."""
    labels = news.EXTRACTED_LABELS
    relationships = news.EXTRACTED_RELATIONSHIPS

    lines = [
        load_prompt("extraction/ontology-heading", version=1),
        "",
        load_prompt("extraction/label-instructions", version=1),
    ]
    lines.extend(f"- `{label}`" for label in sorted(labels))

    lines.extend(["", load_prompt("extraction/sub-labels-heading", version=1), ""])
    for label in sorted(news.SUB_LABELS.keys() & labels):
        allowed = ", ".join(f"`{item}`" for item in sorted(news.SUB_LABELS[label]))
        requirement = (
            load_prompt("extraction/required-sub-label", version=1)
            if label in news.REQUIRED_SUB_LABELS
            else load_prompt("extraction/optional-sub-label", version=1)
        )
        lines.append(
            load_prompt("extraction/sub-label-rule", version=1).format(
                label=label, requirement=requirement, allowed=allowed
            )
        )

    lines.extend(["", load_prompt("extraction/label-properties-heading", version=1), ""])
    for label in sorted(labels):
        properties = ", ".join(f"`{item}`" for item in sorted(news.PROPERTIES[label])) or "none"
        lines.append(
            load_prompt("extraction/label-properties", version=1).format(
                label=label, properties=properties
            )
        )

    lines.extend(
        [
            "",
            (
                load_prompt("extraction/label-property-instructions", version=1)
            ),
            "",
            load_prompt("extraction/relationships-heading", version=1),
            "",
            load_prompt("extraction/relationship-instructions", version=1),
        ]
    )
    for relationship_type, shape in sorted(relationships.items()):
        sources = " or ".join(f"`{item}`" for item in sorted(shape.source_labels))
        targets = " or ".join(f"`{item}`" for item in sorted(shape.target_labels))
        lines.append(
            load_prompt("extraction/relationship-shape", version=1).format(
                relationship_type=relationship_type, sources=sources, targets=targets
            )
        )

    lines.extend(_relationship_property_lines(relationships))
    return "\n".join(lines)
