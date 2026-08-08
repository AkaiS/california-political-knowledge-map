"""Conforming untrusted extraction output to the News Ontology.

This is a pure function over an extraction result: it never logs, never mutates
its input, and never raises on off-ontology output. Everything it refuses is
returned as a drop for the caller to record. The untrusted-input boundary — the
Entity Extraction Adapter — is what calls it; keeping the decision here means
the whole ontology-to-conformance loop is testable without constructing an
adapter or a model.

Node labels are gated on :data:`knowledge_map.ontology.news.EXTRACTED_LABELS`,
not on the full News Ontology label set. ``NewsArticle`` and ``Chunk`` are
written from the article itself, so a model that emits one is guessing: the node
is dropped like any other off-ontology output and the conforming entities beside
it survive.
"""

from dataclasses import dataclass

from knowledge_map.schemas import ExtractionResult, Node, Relationship

from . import news

#: Adherence Report categories a drop can fall into.
REJECTED_LABELS = "rejected_labels"
REJECTED_RELATIONSHIP_TYPES = "rejected_relationship_types"
REJECTED_PROPERTY_NAMES = "rejected_property_names"


@dataclass(frozen=True)
class ConformanceDrop:
    """One item conformance refused, and why."""

    category: str
    value: str
    chunk_id: str
    reason: str


@dataclass(frozen=True)
class ConformanceOutcome:
    """The conformed result together with the drops that produced it."""

    result: ExtractionResult
    drops: tuple[ConformanceDrop, ...]


def conform_extraction_result(result: ExtractionResult, chunk_id: str) -> ConformanceOutcome:
    """Return ``result`` reduced to what the News Ontology admits, plus its drops."""

    drops: list[ConformanceDrop] = []

    def drop(category: str, value: str, reason: str) -> None:
        drops.append(ConformanceDrop(category=category, value=value, chunk_id=chunk_id, reason=reason))

    nodes: list[Node] = []
    for node in result.nodes:
        if node.label not in news.EXTRACTED_LABELS:
            reason = (
                "label is written from the article, not extracted"
                if node.label in news.WRITE_PATH_LABELS
                else "unknown label"
            )
            drop(REJECTED_LABELS, node.label, reason)
            continue

        allowed_sub_labels = news.SUB_LABELS.get(node.label, frozenset())
        invalid_sub_labels = [item for item in node.sub_labels if item not in allowed_sub_labels]
        if invalid_sub_labels:
            for sub_label in invalid_sub_labels:
                drop(REJECTED_LABELS, sub_label, f"unknown sub-label for {node.label}")
            continue
        if node.label in news.REQUIRED_SUB_LABELS and not node.sub_labels:
            drop(REJECTED_LABELS, node.label, "required sub-label is missing")
            continue

        properties = {}
        for name, value in node.properties.items():
            if name not in news.PROPERTIES[node.label]:
                drop(REJECTED_PROPERTY_NAMES, name, f"unknown property for {node.label}")
            else:
                properties[name] = value
        nodes.append(node.model_copy(update={"properties": properties}))

    nodes_by_name = {node.name: node for node in nodes}
    relationships: list[Relationship] = []
    for relationship in result.relationships:
        relationship_type = relationship.relationship_type
        shape = news.RELATIONSHIPS.get(relationship_type)
        if shape is None:
            drop(REJECTED_RELATIONSHIP_TYPES, relationship_type, "unknown relationship type")
            continue

        source = nodes_by_name.get(relationship.source)
        target = nodes_by_name.get(relationship.target)
        if source is None or target is None:
            drop(REJECTED_RELATIONSHIP_TYPES, relationship_type, "dangling endpoint")
            continue
        if source.label not in shape.source_labels or target.label not in shape.target_labels:
            drop(REJECTED_RELATIONSHIP_TYPES, relationship_type, "endpoint labels violate ontology")
            continue
        relationships.append(relationship)

    return ConformanceOutcome(
        result=ExtractionResult(nodes=nodes, relationships=relationships),
        drops=tuple(drops),
    )
