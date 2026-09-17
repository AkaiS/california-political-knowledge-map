"""Compiler-owned semantic pieces and fixed Grounding Evidence paths."""

from dataclasses import asdict, dataclass
from datetime import date
from typing import get_args

from knowledge_map.core.bill_sessions import parse_bill_designation
from knowledge_map.ontology import news
from knowledge_map.schemas.structural import (
    OntologySelection,
    PieceSelection,
    PositionalBindings,
    SemanticLabel,
    SemanticWiring,
)


@dataclass(frozen=True)
class Piece:
    id: str
    kind: str
    label: str
    property: str | None = None
    predicate: str | None = None
    target: str | None = None
    operator: str = "eq"
    alternatives: tuple[str, ...] = ()


class HopBoundError(ValueError):
    pass


_LABELS = get_args(SemanticLabel.__value__)
_PARENT = {
    child: parent
    for parent, children in news.SUB_LABELS.items()
    for child in _LABELS
    if child in children
}

CATALOG = (
    tuple(
        piece
        for label in _LABELS
        for piece in (
            Piece(f"ROLE__{label.upper()}", "role", label),
            *(
                Piece(
                    f"FILTER__{label.upper()}__{prop.upper()}__{operator.upper()}",
                    "filter",
                    label,
                    prop,
                    operator=operator,
                )
                for prop in (
                    ("id", "title", "published_date")
                    if label == "NewsArticle"
                    else ("id", "name", "session")
                    if label == "Bill"
                    else ("id", "name")
                )
                for operator in (
                    ("date_gte", "date_lt") if prop == "published_date" else ("eq",)
                )
            ),
        )
    )
    + tuple(
        Piece(
            f"REL__{source.upper()}__{predicate}__{target.upper()}",
            "relationship",
            source,
            predicate=predicate,
            target=target,
        )
        for predicate, shape in sorted(news.RELATIONSHIPS.items())
        if predicate not in {"HAS_CHUNK", "MENTIONED_IN"}
        for source in _LABELS
        if _PARENT.get(source, source) in shape.source_labels
        for target in _LABELS
        if _PARENT.get(target, target) in shape.target_labels
    )
    + (
        Piece(
            "REL__POLITICIAN__RECORDED_VOTE__LEGISLATIVEEVENT",
            "relationship",
            "Politician",
            target="LegislativeEvent",
            alternatives=("VOTED_AYE", "VOTED_NO", "ABSTAINED"),
        ),
    )
)


def filtered_catalog(selection: OntologySelection) -> tuple[Piece, ...]:
    legal_relationships = {
        predicate
        for p in CATALOG
        if p.kind == "relationship"
        for predicate in (p.alternatives or (p.predicate,))
    }
    if not set(selection.relationships) <= legal_relationships:
        raise ValueError("select only semantic ontology relationships")
    for label, props in selection.filter_properties.items():
        legal = {p.property for p in CATALOG if p.label == label and p.kind == "filter"}
        if label not in selection.labels or not set(props) <= legal:
            raise ValueError("filter properties must belong to selected labels")
    return tuple(
        p
        for p in CATALOG
        if p.label in selection.labels
        and (
            p.kind == "role"
            or p.kind == "filter"
            and p.property in selection.filter_properties.get(p.label, ())
            or p.kind == "relationship"
            and set(p.alternatives or (p.predicate,)) <= set(selection.relationships)
            and p.target in selection.labels
        )
    )


def selected_pieces(
    selection: PieceSelection, catalog: tuple[Piece, ...]
) -> dict[str, tuple[Piece, ...]]:
    if len(selection.relationship_ids) > 3:
        raise HopBoundError("at most three question-semantic relationships are allowed")
    if len(selection.role_ids) > 4:
        raise ValueError("at most four connected roles are allowed")
    by_id = {piece.id: piece for piece in catalog}
    grouped = {}
    for kind, ids in (
        ("role", selection.role_ids),
        ("relationship", selection.relationship_ids),
        ("filter", selection.filter_ids),
    ):
        if any(item not in by_id or by_id[item].kind != kind for item in ids):
            raise ValueError("select only supplied pieces of the requested kind")
        grouped[kind] = tuple(by_id[item] for item in ids)
    return grouped


def validate_wiring(
    wiring: SemanticWiring, pieces: dict[str, tuple[Piece, ...]]
) -> None:
    roles, filters = pieces["role"], pieces["filter"]
    relationships = pieces["relationship"]
    if len(relationships) > 3:
        raise HopBoundError("at most three question-semantic relationships are allowed")
    if relationships:
        if sorted(t.relationship_index for t in wiring.triples) != list(
            range(len(relationships))
        ):
            raise ValueError("wire each selected relationship exactly once")
        connected = {0}
        for triple in wiring.triples:
            source, target = triple.source_role_index, triple.target_role_index
            if source >= len(roles) or target >= len(roles) or source == target:
                raise ValueError(
                    "wire relationships between two distinct selected roles"
                )
            relationship = relationships[triple.relationship_index]
            if (
                roles[source].label != relationship.label
                or roles[target].label != relationship.target
            ):
                raise ValueError(
                    "relationship endpoints must have their declared labels"
                )
        for _ in relationships:
            for triple in wiring.triples:
                endpoints = {triple.source_role_index, triple.target_role_index}
                if connected & endpoints:
                    connected |= endpoints
        if connected != set(range(len(roles))):
            raise ValueError("wire all selected roles into one connected question")
    elif len(roles) != 1 or wiring.triples:
        raise ValueError("entity lookup needs one role and no semantic relationship")
    for pair in wiring.distinct_roles:
        if (
            pair.left_role_index >= len(roles)
            or pair.right_role_index >= len(roles)
            or pair.left_role_index == pair.right_role_index
        ):
            raise ValueError(
                "distinct roles must name two different selected role indices"
            )
    if sorted(item.filter_index for item in wiring.filters) != list(
        range(len(filters))
    ):
        raise ValueError("wire each selected filter exactly once")
    for item in wiring.filters:
        if (
            item.role_index >= len(roles)
            or roles[item.role_index].label != filters[item.filter_index].label
        ):
            raise ValueError("filter must be wired to a role with the same label")


def compile_query(
    pieces: dict[str, tuple[Piece, ...]],
    wiring: SemanticWiring,
    bindings: PositionalBindings,
) -> tuple[str, dict[str, str]]:
    validate_wiring(wiring, pieces)
    if len(bindings.values) != len(wiring.filters):
        raise ValueError("bind one value per wired filter")
    values = list(bindings.values)
    bill_slots = [
        i
        for i, item in enumerate(wiring.filters)
        if pieces["filter"][item.filter_index].label == "Bill"
        and pieces["filter"][item.filter_index].property == "name"
    ]
    if len(bill_slots) > 1:
        if sorted(item.slot_index for item in bindings.bill_names) != bill_slots:
            raise ValueError(
                "assign each Bill-name slot exactly once through bill_names"
            )
        for assignment in bindings.bill_names:
            if values[assignment.slot_index] is not None:
                raise ValueError(
                    "leave positional Bill-name values null when using bill_names"
                )
            values[assignment.slot_index] = assignment.value
    elif bindings.bill_names:
        raise ValueError(
            "use positional values when there is at most one Bill-name slot"
        )
    for slot in bill_slots:
        designation = parse_bill_designation(values[slot])
        if designation is None:
            raise ValueError(
                f"Bill-name slot {slot} needs a recognized Bill Designation: SB N, AB N, Senate Bill N, or Assembly Bill N"
            )
        values[slot] = designation
    identities = set()
    for slot in bill_slots:
        role_index = wiring.filters[slot].role_index
        sessions = tuple(
            values[i]
            for i, item in enumerate(wiring.filters)
            if item.role_index == role_index
            and pieces["filter"][item.filter_index].property == "session"
        )
        identity = (values[slot], sessions)
        if identity in identities:
            raise ValueError(
                "assign distinct Bill Designations or sessions to separate Bill-name slots; do not repeat one Bill across all slots"
            )
        identities.add(identity)
    if any(value is None for value in values):
        raise ValueError("bind a nonempty value to every filter slot")
    roles = pieces["role"]

    def node(index: int) -> str:
        label = roles[index].label
        labels = f"{_PARENT[label]}:{label}" if label in _PARENT else label
        return f"(role_{index}:{labels})"

    if wiring.triples:
        clauses = [
            f"MATCH {node(t.source_role_index)}-[semantic_rel_{t.relationship_index}:{'|'.join(relationship.alternatives) or relationship.predicate}]->{node(t.target_role_index)}"
            for t in wiring.triples
            for relationship in (pieces["relationship"][t.relationship_index],)
        ]
    else:
        clauses = [f"MATCH {node(0)}"]
    parameters = {f"parameter_{i}": v for i, v in enumerate(values) if v is not None}
    constraints = [
        f"role_{pair.left_role_index}.id <> role_{pair.right_role_index}.id"
        for pair in wiring.distinct_roles
    ]
    for i, item in enumerate(wiring.filters):
        piece = pieces["filter"][item.filter_index]
        property_expression = f"role_{item.role_index}.{piece.property}"
        if piece.operator == "eq":
            constraints.append(f"{property_expression} = $parameter_{i}")
        else:
            parameters[f"parameter_{i}"] = date.fromisoformat(
                parameters[f"parameter_{i}"]
            ).isoformat()
            operator = ">=" if piece.operator == "date_gte" else "<"
            constraints.append(
                f"date(substring({property_expression}, 0, 10)) {operator} date($parameter_{i})"
            )
    if constraints:
        clauses.append("WHERE " + " AND ".join(constraints))
    if wiring.triples:
        hydration = []
        claims = []
        for triple in sorted(wiring.triples, key=lambda t: t.relationship_index):
            source, target = triple.source_role_index, triple.target_role_index
            relation = f"semantic_rel_{triple.relationship_index}"
            predicate = pieces["relationship"][triple.relationship_index].predicate
            branch = [f"WITH role_{source}, role_{target}, {relation}"]
            if predicate == "DISCUSSES_TOPIC":
                branch.extend(
                    (
                        f"OPTIONAL MATCH (role_{source})-[:HAS_CHUNK]->(c:Chunk)",
                        f"WITH c, role_{source} AS a",
                    )
                )
            elif predicate == "ABOUT_TOPIC":
                branch.extend(
                    (
                        (
                            f"UNWIND CASE WHEN size(coalesce({relation}.articles, [])) = 0 "
                            f"THEN [null] ELSE {relation}.articles END AS asserting_article_id"
                        ),
                        "OPTIONAL MATCH (a:NewsArticle {id: asserting_article_id})-[:HAS_CHUNK]->(c:Chunk)",
                    )
                )
            else:
                branch.extend(
                    (
                        (
                            f"UNWIND CASE WHEN size(coalesce({relation}.chunks, [])) = 0 "
                            f"THEN [null] ELSE {relation}.chunks END AS asserting_chunk_id"
                        ),
                        (
                            f"OPTIONAL MATCH (role_{source})-[:MENTIONED_IN]->"
                            f"(c:Chunk {{id: asserting_chunk_id}})<-[:MENTIONED_IN]-(role_{target})"
                        ),
                        "OPTIONAL MATCH (a:NewsArticle)-[:HAS_CHUNK]->(c)",
                    )
                )
            branch.append("RETURN c, a")
            hydration.append("\n".join(branch))
            claims.append(
                "{relationship_type: type("
                + relation
                + "), claim_properties: properties("
                + relation
                + "), "
                f"source_id: role_{source}.id, source_element_id: elementId(role_{source}), "
                f"target_id: role_{target}.id, target_element_id: elementId(role_{target})"
                + "}"
            )
        clauses.append("CALL {\n" + "\nUNION ALL\n".join(hydration) + "\n}")
        claim_fields = "[" + ", ".join(claims) + "] AS claims, "
    else:
        if roles[0].label == "NewsArticle":
            clauses.extend(
                ("MATCH (role_0)-[:HAS_CHUNK]->(c:Chunk)", "WITH *, role_0 AS a")
            )
        elif roles[0].label == "PolicyArea":
            clauses.append(
                "MATCH (role_0)<-[:DISCUSSES_TOPIC]-(a:NewsArticle)-[:HAS_CHUNK]->(c:Chunk)"
            )
        else:
            clauses.append(
                "MATCH (role_0)-[:MENTIONED_IN]->(c:Chunk)<-[:HAS_CHUNK]-(a:NewsArticle)"
            )
        claim_fields = ""
    clauses.append(
        "RETURN DISTINCT "
        + claim_fields
        + "c.id AS chunk_id, c.text AS text, a.id AS source_article_id, "
        "a.title AS title, coalesce(a.url, a.id) AS url, a.published_date AS published_date, "
        "role_0.id AS entry_id, elementId(role_0) AS element_id "
        "ORDER BY chunk_id, source_article_id, element_id"
    )
    return "\n".join(clauses), parameters


def public_pieces(pieces: tuple[Piece, ...]) -> list[dict]:
    return [asdict(piece) for piece in pieces]
