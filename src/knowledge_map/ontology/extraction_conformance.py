"""Conforming untrusted extraction output to the News Ontology.

Called by the Entity Extraction Adapter.  A pure function over an extraction
result: it never logs, never mutates its input, and never raises.  Everything
it refuses comes back as a drop for the caller to record.

Node labels are gated on :data:`knowledge_map.ontology.news.EXTRACTED_LABELS`
and relationship types on
:data:`knowledge_map.ontology.news.EXTRACTED_RELATIONSHIPS`, rather than on
the full ontology, so a label or relationship another stage owns -- an emitted
``NewsArticle``, or a ``PolicyArea`` and its topic edge -- is dropped and the
entities beside it survive.  Undeclared relationship properties are dropped
under their own Adherence Report category and the relationship survives them.
"""

from pydantic import BaseModel, ConfigDict

from knowledge_map.schemas import DropCategory, ExtractionResult, Node, Relationship

from . import news


class ConformanceDrop(BaseModel):
    """One item conformance refused, and why.

    The category is drawn from the closed :class:`DropCategory` enumeration, so a
    drop recorded under a name the Adherence Report does not know is a
    construction-time error rather than a bucket nobody reads.
    """

    model_config = ConfigDict(frozen=True)

    category: DropCategory
    value: str
    chunk_id: str
    reason: str


class ConformanceOutcome(BaseModel):
    """The conformed result together with the drops that produced it."""

    model_config = ConfigDict(frozen=True)

    result: ExtractionResult
    drops: tuple[ConformanceDrop, ...]


def _resolve_endpoint(admitted: set[str], claimed: str | None) -> str | None:
    """The one label an endpoint means, or ``None`` where nothing can say.

    Pass every label a node of the endpoint's name carries that the
    relationship's shape allows.  A single admitted label wins outright;
    ``claimed`` decides only among several, and only by naming one of them.
    """

    if len(admitted) == 1:
        return next(iter(admitted))
    return claimed if claimed in admitted else None


def _unextracted_relationship_reason(relationship_type: str) -> str:
    """Why a declared relationship is still not one a chunk may claim.

    A relationship leaves the extractor's list by touching a label the
    extractor does not produce, so the reason is read off the endpoint that
    took it out rather than restated per type.
    """

    shape = news.RELATIONSHIPS.get(relationship_type)
    if shape is None:
        return "unknown relationship type"
    endpoints = shape.source_labels | shape.target_labels
    if endpoints & news.STAGE_DECIDED_LABELS:
        return "relationship is decided once per article, not extracted from a chunk"
    return "relationship is written from the article, not extracted"


def conform_extraction_result(result: ExtractionResult, chunk_id: str) -> ConformanceOutcome:
    """Return ``result`` reduced to what the News Ontology admits, plus its drops."""

    drops: list[ConformanceDrop] = []

    def drop(category: DropCategory, value: str, reason: str) -> None:
        drops.append(ConformanceDrop(category=category, value=value, chunk_id=chunk_id, reason=reason))

    nodes: list[Node] = []
    for node in result.nodes:
        if node.label not in news.EXTRACTED_LABELS:
            if node.label in news.WRITE_PATH_LABELS:
                reason = "label is written from the article, not extracted"
            elif node.label in news.STAGE_DECIDED_LABELS:
                reason = "label is decided once per article, not extracted from a chunk"
            else:
                reason = "unknown label"
            drop(DropCategory.REJECTED_LABELS, node.label, reason)
            continue

        allowed_sub_labels = news.SUB_LABELS.get(node.label, frozenset())
        invalid_sub_labels = [item for item in node.sub_labels if item not in allowed_sub_labels]
        if invalid_sub_labels:
            for sub_label in invalid_sub_labels:
                drop(DropCategory.REJECTED_LABELS, sub_label, f"unknown sub-label for {node.label}")
            continue
        if node.label in news.REQUIRED_SUB_LABELS and not node.sub_labels:
            drop(DropCategory.REJECTED_LABELS, node.label, "required sub-label is missing")
            continue

        properties = {}
        for name, value in node.properties.items():
            if name not in news.PROPERTIES[node.label]:
                drop(DropCategory.REJECTED_PROPERTY_NAMES, name, f"unknown property for {node.label}")
            else:
                properties[name] = value
        nodes.append(node.model_copy(update={"properties": properties}))

    # A name is not a key: two nodes can share one under different labels, so
    # an endpoint collects every node carrying the name and the ontology picks
    # among them.
    nodes_by_name: dict[str, list[Node]] = {}
    for node in nodes:
        nodes_by_name.setdefault(node.name, []).append(node)

    relationships: list[Relationship] = []
    for relationship in result.relationships:
        relationship_type = relationship.relationship_type
        shape = news.EXTRACTED_RELATIONSHIPS.get(relationship_type)
        if shape is None:
            drop(
                DropCategory.REJECTED_RELATIONSHIP_TYPES,
                relationship_type,
                _unextracted_relationship_reason(relationship_type),
            )
            continue

        sources = nodes_by_name.get(relationship.source, [])
        targets = nodes_by_name.get(relationship.target, [])
        if not sources or not targets:
            drop(DropCategory.REJECTED_RELATIONSHIP_TYPES, relationship_type, "dangling endpoint")
            continue

        source_labels = {node.label for node in sources if node.label in shape.source_labels}
        target_labels = {node.label for node in targets if node.label in shape.target_labels}
        if not source_labels or not target_labels:
            drop(DropCategory.REJECTED_RELATIONSHIP_TYPES, relationship_type, "endpoint labels violate ontology")
            continue

        source_label = _resolve_endpoint(source_labels, relationship.source_label)
        target_label = _resolve_endpoint(target_labels, relationship.target_label)
        if source_label is None or target_label is None:
            drop(DropCategory.REJECTED_RELATIONSHIP_TYPES, relationship_type, "ambiguous endpoint")
            continue

        # An undeclared relationship property is dropped under its own
        # category, so edge payload reads separately from invented node
        # fields.  The relationship survives its own property drops.
        properties = {}
        for name, value in relationship.properties.items():
            if name not in shape.property_names:
                drop(
                    DropCategory.REJECTED_RELATIONSHIP_PROPERTY_NAMES,
                    name,
                    f"unknown property for {relationship_type}",
                )
            else:
                properties[name] = value
        # The resolved labels ride along with the edge, so persistence never
        # re-derives them from the name alone.
        relationships.append(
            relationship.model_copy(
                update={
                    "properties": properties,
                    "source_label": source_label,
                    "target_label": target_label,
                }
            )
        )

    return ConformanceOutcome(
        result=ExtractionResult(nodes=nodes, relationships=relationships),
        drops=tuple(drops),
    )
