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


_LABELS = get_args(SemanticLabel.__value__)
_PARENT = {
    child: parent
    for parent, children in news.SUB_LABELS.items()
    for child in _LABELS
    if child in children
}

CATALOG = tuple(
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
) + tuple(
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


def filtered_catalog(selection: OntologySelection) -> tuple[Piece, ...]:
    legal_relationships = {p.predicate for p in CATALOG if p.kind == "relationship"}
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
            and p.predicate in selection.relationships
            and p.target in selection.labels
        )
    )


def selected_pieces(
    selection: PieceSelection, catalog: tuple[Piece, ...]
) -> dict[str, tuple[Piece, ...]]:
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
    if relationships:
        if len(relationships) != 1 or len(roles) != 2:
            raise ValueError("one relationship needs exactly two roles")
        if len(wiring.triples) != 1:
            raise ValueError("wire the selected relationship exactly once")
        triple = wiring.triples[0]
        if triple.relationship_index != 0 or {
            triple.source_role_index,
            triple.target_role_index,
        } != {0, 1}:
            raise ValueError(
                "wire the selected relationship between its two distinct roles"
            )
        relationship = relationships[0]
        if (
            roles[triple.source_role_index].label != relationship.label
            or roles[triple.target_role_index].label != relationship.target
        ):
            raise ValueError("relationship endpoints must have their declared labels")
    elif len(roles) != 1 or wiring.triples:
        raise ValueError("entity lookup needs one role and no semantic relationship")
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
    roles = pieces["role"]

    def node(index: int) -> str:
        label = roles[index].label
        labels = f"{_PARENT[label]}:{label}" if label in _PARENT else label
        return f"(role_{index}:{labels})"

    if wiring.triples:
        triple = wiring.triples[0]
        source, target = triple.source_role_index, triple.target_role_index
        clauses = [
            f"MATCH {node(source)}-[semantic_rel_0:{pieces['relationship'][0].predicate}]->{node(target)}"
        ]
    else:
        clauses = [f"MATCH {node(0)}"]
    parameters = {f"parameter_{i}": v for i, v in enumerate(bindings.values)}
    constraints = []
    for i, item in enumerate(wiring.filters):
        piece = pieces["filter"][item.filter_index]
        if piece.label == "Bill" and piece.property == "name":
            designation = parse_bill_designation(bindings.values[i])
            if designation is None:
                raise ValueError("Bill name must contain a recognized Bill Designation")
            parameters[f"parameter_{i}"] = designation
        property_expression = f"role_{item.role_index}.{piece.property}"
        if piece.operator == "eq":
            constraints.append(f"{property_expression} = $parameter_{i}")
        else:
            parameters[f"parameter_{i}"] = date.fromisoformat(
                bindings.values[i]
            ).isoformat()
            operator = ">=" if piece.operator == "date_gte" else "<"
            constraints.append(
                f"date(substring({property_expression}, 0, 10)) {operator} date($parameter_{i})"
            )
    if constraints:
        clauses.append("WHERE " + " AND ".join(constraints))
    if wiring.triples:
        predicate = pieces["relationship"][0].predicate
        if predicate == "DISCUSSES_TOPIC":
            clauses.extend(
                (
                    f"OPTIONAL MATCH (role_{source})-[:HAS_CHUNK]->(c:Chunk)",
                    f"WITH *, role_{source} AS a",
                )
            )
        elif predicate == "ABOUT_TOPIC":
            clauses.extend(
                (
                    (
                        "UNWIND CASE WHEN size(coalesce(semantic_rel_0.articles, [])) = 0 "
                        "THEN [null] ELSE semantic_rel_0.articles END AS asserting_article_id"
                    ),
                    "OPTIONAL MATCH (a:NewsArticle {id: asserting_article_id})-[:HAS_CHUNK]->(c:Chunk)",
                )
            )
        else:
            clauses.extend(
                (
                    (
                        "UNWIND CASE WHEN size(coalesce(semantic_rel_0.chunks, [])) = 0 "
                        "THEN [null] ELSE semantic_rel_0.chunks END AS asserting_chunk_id"
                    ),
                    (
                        f"OPTIONAL MATCH (role_{source})-[:MENTIONED_IN]->"
                        f"(c:Chunk {{id: asserting_chunk_id}})<-[:MENTIONED_IN]-(role_{target})"
                    ),
                    "OPTIONAL MATCH (a:NewsArticle)-[:HAS_CHUNK]->(c)",
                )
            )
        claim_fields = (
            "type(semantic_rel_0) AS relationship_type, properties(semantic_rel_0) AS claim_properties, "
            f"role_{source}.id AS source_id, elementId(role_{source}) AS source_element_id, "
            f"role_{target}.id AS target_id, elementId(role_{target}) AS target_element_id, "
        )
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
