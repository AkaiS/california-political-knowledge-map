"""Semantic atomic pieces. Storage and result-shaping pieces are absent."""

from dataclasses import asdict, dataclass
from typing import Literal

from knowledge_map.ontology import news
from knowledge_map.prototypes.composable_triples.compiler import NODE_PROPERTIES
from knowledge_map.prototypes.composable_triples.contracts import (
    ConstraintOperator,
    NodeLabel,
    Predicate,
    PropertyName,
)

PieceKind = Literal["role", "relationship", "filter", "role_constraint", "aggregation"]
COMPILER_LABELS = tuple(label for label in NodeLabel if label != NodeLabel.CHUNK)
SEMANTIC_LABELS = tuple(
    label for label in COMPILER_LABELS if label != NodeLabel.NEWS_ARTICLE
)
SEMANTIC_PREDICATES = tuple(
    predicate
    for predicate in Predicate
    if predicate not in {Predicate.HAS_CHUNK, Predicate.MENTIONED_IN}
)


@dataclass(frozen=True)
class Piece:
    piece_id: str
    kind: PieceKind
    description: str
    source_label: NodeLabel | None = None
    predicates: tuple[Predicate, ...] = ()
    target_label: NodeLabel | None = None
    node_label: NodeLabel | None = None
    property: PropertyName | None = None
    operator: ConstraintOperator | None = None
    group_label: NodeLabel | None = None
    count_label: NodeLabel | None = None

    def public(self) -> dict:
        value = asdict(self)
        return {
            key: _value(item) for key, item in value.items() if item not in (None, ())
        }


def _value(item):
    if isinstance(item, tuple):
        return [_value(value) for value in item]
    return getattr(item, "value", item)


PARENT = {NodeLabel.LABOR_UNION: "Organization", NodeLabel.PAC: "Organization"}


def _variants(base: str) -> tuple[NodeLabel, ...]:
    return tuple(
        label for label in COMPILER_LABELS if PARENT.get(label, label.value) == base
    )


def _id(*parts: object) -> str:
    return "__".join(
        (
            "ARTICLE"
            if part == NodeLabel.NEWS_ARTICLE
            else str(getattr(part, "value", part)).upper()
        )
        for part in parts
    )


def _label_name(label: NodeLabel) -> str:
    return "article" if label == NodeLabel.NEWS_ARTICLE else label.value


def _pieces() -> list[Piece]:
    pieces: list[Piece] = []
    for label in SEMANTIC_LABELS:
        pieces.append(
            Piece(
                _id("ROLE", label),
                "role",
                f"one semantic {label.value} role",
                node_label=label,
            )
        )
    representable = {PARENT.get(label, label.value) for label in COMPILER_LABELS}
    for predicate in SEMANTIC_PREDICATES:
        shape = news.RELATIONSHIPS[predicate.value]
        for source in sorted(shape.source_labels & representable):
            for target in sorted(shape.target_labels & representable):
                for source_label in _variants(source):
                    for target_label in _variants(target):
                        pieces.append(
                            Piece(
                                _id("REL", source_label, predicate, target_label),
                                "relationship",
                                f"one semantic triple: {_label_name(source_label)} -{predicate.value}-> {_label_name(target_label)}",
                                source_label=source_label,
                                predicates=(predicate,),
                                target_label=target_label,
                            )
                        )
    for source, predicates, target in (
        (
            NodeLabel.ORGANIZATION,
            (Predicate.LOBBIED_FOR, Predicate.LOBBIED_AGAINST),
            NodeLabel.BILL,
        ),
        (
            NodeLabel.POLITICIAN,
            (Predicate.VOTED_AYE, Predicate.VOTED_NO, Predicate.ABSTAINED),
            NodeLabel.LEGISLATIVE_EVENT,
        ),
    ):
        pieces.append(
            Piece(
                _id(
                    "REL_ANY",
                    source,
                    "_OR_".join(item.value for item in predicates),
                    target,
                ),
                "relationship",
                f"one semantic predicate-alternative triple: {source.value} -{{{'|'.join(item.value for item in predicates)}}}-> {target.value}",
                source_label=source,
                predicates=predicates,
                target_label=target,
            )
        )
    filterable = {
        PropertyName.NAME,
        PropertyName.SESSION,
        PropertyName.TITLE,
        PropertyName.PUBLISHED_DATE,
    }
    for label in COMPILER_LABELS:
        for prop in sorted(
            NODE_PROPERTIES[label] & filterable, key=lambda item: item.value
        ):
            operators = (
                (ConstraintOperator.DATE_GTE, ConstraintOperator.DATE_LT)
                if prop == PropertyName.PUBLISHED_DATE
                else (ConstraintOperator.EQ,)
            )
            for operator in operators:
                pieces.append(
                    Piece(
                        _id("FILTER", label, prop, operator),
                        "filter",
                        f"filter one {_label_name(label)} role by {prop.value} using {operator.value}",
                        node_label=label,
                        property=prop,
                        operator=operator,
                    )
                )
        if label != NodeLabel.NEWS_ARTICLE:
            pieces.append(
                Piece(
                    _id("DISTINCT", label, "ROLES"),
                    "role_constraint",
                    f"require two {label.value} roles to identify different entities",
                    node_label=label,
                    property=PropertyName.ID,
                )
            )
    pieces.append(
        Piece(
            "AGG__POLICYAREA__COUNT_ARTICLE",
            "aggregation",
            "group by PolicyArea and count distinct articles",
            group_label=NodeLabel.POLICY_AREA,
            count_label=NodeLabel.NEWS_ARTICLE,
        )
    )
    return sorted(pieces, key=lambda item: (item.kind, item.piece_id))


CATALOG = tuple(_pieces())
BY_ID = {piece.piece_id: piece for piece in CATALOG}
COMPILER_NEWS_ARTICLE_ROLE = Piece(
    "COMPILER__ARTICLE_ROLE",
    "role",
    "compiler-owned article role",
    node_label=NodeLabel.NEWS_ARTICLE,
)


def public_catalog() -> list[dict]:
    return [piece.public() for piece in CATALOG]
