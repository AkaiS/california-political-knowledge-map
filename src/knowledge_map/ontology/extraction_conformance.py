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

The drop-and-log rule holds on both sides of an edge. A relationship property the
relationship's shape does not declare is dropped exactly as an undeclared node
property is, under its own Adherence Report category; the relationship survives
its own property drops, because an edge whose detail was refused still asserts
that the claim exists.
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

    ``admitted`` is every label carried by a node of the endpoint's name that the
    relationship's shape allows. One is the answer, whatever the extractor claimed:
    where the ontology leaves no choice there is nothing for a model's label to add,
    and a wrong claim must not cost a fact the ontology already resolved.

    More than one is a genuine choice the shape cannot make — ``ENDORSED`` admits
    both a Politician and an Organization, so a name that is both says nothing about
    who endorsed. Only there does the extractor's label decide, and only by picking
    from the labels already admitted. A claim naming none of them decides nothing,
    and the endpoint stays unresolved rather than resolving to a coin flip.
    """

    if len(admitted) == 1:
        return next(iter(admitted))
    return claimed if claimed in admitted else None


def conform_extraction_result(result: ExtractionResult, chunk_id: str) -> ConformanceOutcome:
    """Return ``result`` reduced to what the News Ontology admits, plus its drops."""

    drops: list[ConformanceDrop] = []

    def drop(category: DropCategory, value: str, reason: str) -> None:
        drops.append(ConformanceDrop(category=category, value=value, chunk_id=chunk_id, reason=reason))

    nodes: list[Node] = []
    for node in result.nodes:
        if node.label not in news.EXTRACTED_LABELS:
            reason = (
                "label is written from the article, not extracted"
                if node.label in news.WRITE_PATH_LABELS
                else "unknown label"
            )
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

    # A name is not a key. Two conforming nodes can share a canonical name under
    # different labels ("Newsom" the Politician and "Newsom" the Organization), so
    # an endpoint resolves to every node that carries the name and the ontology
    # picks among them. Keeping only the last one would silently validate the edge
    # against the wrong label — discarding a true claim, or admitting a false one.
    nodes_by_name: dict[str, list[Node]] = {}
    for node in nodes:
        nodes_by_name.setdefault(node.name, []).append(node)

    relationships: list[Relationship] = []
    for relationship in result.relationships:
        relationship_type = relationship.relationship_type
        shape = news.RELATIONSHIPS.get(relationship_type)
        if shape is None:
            drop(DropCategory.REJECTED_RELATIONSHIP_TYPES, relationship_type, "unknown relationship type")
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

        # Relationship properties are write-path-owned: an undeclared one is dropped
        # like an undeclared node property, but recorded under its own category so a
        # model attaching payload to edges is visible separately from one inventing
        # node fields. The relationship itself survives — losing every property it
        # carried costs the edge its detail, never its existence.
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
        # The resolution rides along with the edge. Conformance is the only place
        # that knows which of the nodes sharing a name this claim is about, and
        # persistence would otherwise have to re-derive it from the name alone —
        # the same collapse, one layer down.
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
