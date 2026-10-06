"""PROTOTYPE: complete semantic fragments and deterministic implication rules."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from knowledge_map.prototypes.atomic_deterministic_hydration.catalog import (
    BY_ID,
    CATALOG,
    Piece,
)

SELECTION_FIELDS = (
    "role_ids",
    "relationship_ids",
    "filter_ids",
    "role_constraint_ids",
    "aggregation_ids",
)


def _role_id(label: object) -> str:
    return f"ROLE__{getattr(label, 'value', label).upper()}"


def _selectable_role_ids(*labels: object) -> tuple[str, ...]:
    return tuple(
        _role_id(label)
        for label in labels
        if getattr(label, "value", label) != "NewsArticle"
    )


def _distinct_id(label: object) -> str:
    return f"DISTINCT__{getattr(label, 'value', label).upper()}__ROLES"


def _empty_counts() -> dict[str, Counter[str]]:
    return {field: Counter() for field in SELECTION_FIELDS}


@dataclass(frozen=True)
class Fragment:
    fragment_id: str
    description: str
    model_shape: dict[str, Any]
    implications: dict[str, tuple[str, ...]]
    competition_group: str | None = None
    variant: str = ""

    def prompt(self) -> dict[str, Any]:
        return {
            "decision": "Does answering the question require this complete semantic fragment?",
            "fragment": self.model_shape,
            "meaning": self.description,
            "rules": [
                "Answer yes only when the whole fragment belongs in the minimal query pattern.",
                "Do not select it because one entity or term is merely related to the question.",
                "Stored-reporting provenance and output formatting are automatic.",
            ],
        }


def _entity_fragments() -> Iterable[Fragment]:
    for piece in CATALOG:
        if piece.kind != "role":
            continue
        label = piece.node_label.value
        yield Fragment(
            fragment_id=f"CONTEXT__{label.upper()}",
            description=(
                f"One {label} participates without a selectable ontology relationship, "
                "for example as an entity mentioned in or returned through stored-reporting context."
            ),
            model_shape={
                "entity": label,
                "use": "entity-only or automatic stored-reporting context",
            },
            implications={"role_ids": (piece.piece_id,)},
        )


def _relationship_description(piece: Piece, peer_side: str | None = None) -> str:
    source = piece.source_label.value
    target = piece.target_label.value
    predicate = " or ".join(item.value for item in piece.predicates)
    if peer_side == "source":
        return (
            f"Two different {source} entities each have the recorded {predicate} relationship "
            f"to the same {target}. This is the complete anchor-and-peer pattern for wording "
            f"such as 'other {source} entities alongside'."
        )
    if peer_side == "target":
        return (
            f"The same {source} has the recorded {predicate} relationship to two different "
            f"{target} entities. This is the complete anchor-and-peer pattern for wording "
            f"such as 'other {target} entities alongside'."
        )
    return f"One {source} has a recorded {predicate} relationship to one {target}."


def _relationship_shape(piece: Piece, peer_side: str | None = None) -> dict[str, Any]:
    source = piece.source_label.value
    target = piece.target_label.value
    predicates = [item.value for item in piece.predicates]
    if peer_side == "source":
        return {
            "entities": [f"anchor {source}", f"different peer {source}", f"shared {target}"],
            "relationships": [
                {"source": f"anchor {source}", "predicate": predicates, "target": f"shared {target}"},
                {"source": f"peer {source}", "predicate": predicates, "target": f"shared {target}"},
            ],
            "constraint": f"anchor {source} and peer {source} must be different entities",
        }
    if peer_side == "target":
        return {
            "entities": [f"shared {source}", f"anchor {target}", f"different peer {target}"],
            "relationships": [
                {"source": f"shared {source}", "predicate": predicates, "target": f"anchor {target}"},
                {"source": f"shared {source}", "predicate": predicates, "target": f"peer {target}"},
            ],
            "constraint": f"anchor {target} and peer {target} must be different entities",
        }
    return {
        "source_entity": source,
        "relationship": predicates,
        "target_entity": target,
    }


def _relationship_fragments() -> Iterable[Fragment]:
    for piece in CATALOG:
        if piece.kind != "relationship":
            continue
        source_role_ids = _selectable_role_ids(piece.source_label)
        target_role_ids = _selectable_role_ids(piece.target_label)
        group = f"RELATIONSHIP_VARIANTS__{piece.source_label.value}__{piece.target_label.value}"
        yield Fragment(
            fragment_id=f"SINGLE__{piece.piece_id}",
            description=_relationship_description(piece),
            model_shape=_relationship_shape(piece),
            implications={
                "role_ids": source_role_ids + target_role_ids,
                "relationship_ids": (piece.piece_id,),
            },
            competition_group=group,
            variant="single",
        )
        if piece.source_label != piece.target_label:
            yield Fragment(
                fragment_id=f"PEER_SOURCE__{piece.piece_id}",
                description=_relationship_description(piece, "source"),
                model_shape=_relationship_shape(piece, "source"),
                implications={
                    "role_ids": source_role_ids + source_role_ids + target_role_ids,
                    "relationship_ids": (piece.piece_id, piece.piece_id),
                    "role_constraint_ids": (_distinct_id(piece.source_label),),
                },
                competition_group=group,
                variant="peer_source",
            )
            yield Fragment(
                fragment_id=f"PEER_TARGET__{piece.piece_id}",
                description=_relationship_description(piece, "target"),
                model_shape=_relationship_shape(piece, "target"),
                implications={
                    "role_ids": source_role_ids + target_role_ids + target_role_ids,
                    "relationship_ids": (piece.piece_id, piece.piece_id),
                    "role_constraint_ids": (_distinct_id(piece.target_label),),
                },
                competition_group=group,
                variant="peer_target",
            )


def _filter_fragments() -> Iterable[Fragment]:
    for piece in CATALOG:
        if piece.kind != "filter":
            continue
        label = piece.node_label.value
        prop = piece.property.value
        operator = piece.operator.value
        meaning = (
            f"One {label} is restricted by an explicit {prop} value from the question "
            f"using the {operator} comparison. Selecting this fragment also supplies the {label} role."
        )
        yield Fragment(
            fragment_id=f"ANCHOR__{piece.piece_id}",
            description=meaning,
            model_shape={
                "entity": label,
                "condition": {"property": prop, "comparison": operator},
                "value_source": "explicit wording in the natural-language question",
            },
            implications={
                "role_ids": _selectable_role_ids(piece.node_label),
                "filter_ids": (piece.piece_id,),
            },
        )


def _aggregate_fragments() -> Iterable[Fragment]:
    relationship = BY_ID["REL__ARTICLE__DISCUSSES_TOPIC__POLICYAREA"]
    for piece in CATALOG:
        if piece.kind != "aggregation":
            continue
        yield Fragment(
            fragment_id=f"COMPLETE__{piece.piece_id}",
            description=(
                "Group Policy Areas, count distinct stored News Articles that discuss each area, "
                "and retain the source articles behind the count."
            ),
            model_shape={
                "source_entity": relationship.source_label.value,
                "relationship": [item.value for item in relationship.predicates],
                "target_entity": relationship.target_label.value,
                "group_by": piece.group_label.value,
                "count_distinct": piece.count_label.value,
            },
            implications={
                "role_ids": _selectable_role_ids(
                    piece.count_label, piece.group_label
                ),
                "relationship_ids": (relationship.piece_id,),
                "aggregation_ids": (piece.piece_id,),
            },
        )


FRAGMENTS = (
    *_entity_fragments(),
    *_relationship_fragments(),
    *_filter_fragments(),
    *_aggregate_fragments(),
)
BY_FRAGMENT_ID = {fragment.fragment_id: fragment for fragment in FRAGMENTS}


def _max_merge(target: dict[str, Counter[str]], implications: dict[str, tuple[str, ...]]) -> None:
    for field, ids in implications.items():
        incoming = Counter(ids)
        for piece_id, count in incoming.items():
            target[field][piece_id] = max(target[field][piece_id], count)


def select_fragments(scores: dict[str, float], threshold: float = 0.5) -> dict[str, Any]:
    """Select complete fragments and expand their compiler-owned implications."""

    missing = set(BY_FRAGMENT_ID) - set(scores)
    if missing:
        raise ValueError(f"missing {len(missing)} fragment scores")

    selected = [
        fragment
        for fragment in FRAGMENTS
        if scores[fragment.fragment_id] >= threshold and fragment.competition_group is None
    ]
    groups = {
        fragment.competition_group
        for fragment in FRAGMENTS
        if fragment.competition_group is not None
    }
    for group in groups:
        winner = max(
            (fragment for fragment in FRAGMENTS if fragment.competition_group == group),
            key=lambda fragment: scores[fragment.fragment_id],
        )
        if scores[winner.fragment_id] >= threshold:
            selected.append(winner)
    selected.sort(key=lambda fragment: fragment.fragment_id)
    counts = _empty_counts()
    for fragment in selected:
        _max_merge(counts, fragment.implications)

    selection = {
        field: [piece_id for piece_id, count in sorted(counts[field].items()) for _ in range(count)]
        for field in SELECTION_FIELDS
    }
    return {
        "threshold": threshold,
        "selected_fragment_ids": [fragment.fragment_id for fragment in selected],
        "selection": selection,
    }


def counter(selection: dict[str, Any]) -> Counter[str]:
    return Counter(piece_id for field in SELECTION_FIELDS for piece_id in selection[field])


def score_selection(actual: dict[str, Any], expected: dict[str, Any]) -> dict[str, Any]:
    actual_counts = counter(actual)
    expected_counts = counter(expected)
    true_positive = sum((actual_counts & expected_counts).values())
    selected = sum(actual_counts.values())
    required = sum(expected_counts.values())
    precision = true_positive / selected if selected else 0.0
    recall = true_positive / required if required else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "exact": actual_counts == expected_counts,
        "true_positive_occurrences": true_positive,
        "selected_occurrences": selected,
        "required_occurrences": required,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "missing": dict(expected_counts - actual_counts),
        "extra": dict(actual_counts - expected_counts),
    }
