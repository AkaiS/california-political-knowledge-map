"""PROTOTYPE: prune complete semantic fragments with a frozen schema selection."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from fragment_selector import (
    Fragment,
    _aggregate_fragments,
    _entity_fragments,
    _filter_fragments,
)
from fragment_selector import _relationship_fragments as all_relationship_fragments
from knowledge_map.prototypes.atomic_deterministic_hydration.catalog import BY_ID


@dataclass(frozen=True)
class NormalizedSubgraph:
    labels: tuple[str, ...]
    predicates: tuple[str, ...]
    filterable_properties: dict[str, tuple[str, ...]]
    reporting_context: bool

    def public(self) -> dict[str, Any]:
        return {
            "entities": list(self.labels),
            "relationships": list(self.predicates),
            "filterable_properties": {
                label: list(properties)
                for label, properties in self.filterable_properties.items()
            },
            "automatic_stored_reporting_context": self.reporting_context,
        }


def normalize_schema(schema: dict[str, Any]) -> NormalizedSubgraph:
    """Turn the frozen filter response into a stable candidate-generation boundary."""

    raw_labels = list(schema["labels"])
    predicates = tuple(dict.fromkeys(schema["relationships"]))
    article_filter_keys = {"Article", "NewsArticle"} & set(
        schema.get("filter_properties", {})
    )
    if "DISCUSSES_TOPIC" in predicates or article_filter_keys:
        raw_labels.append("NewsArticle")
    labels = tuple(dict.fromkeys(raw_labels))
    filterable: dict[str, list[str]] = {label: [] for label in labels}
    for fragment in _filter_fragments():
        label = fragment.model_shape["entity"]
        if label in filterable:
            prop = fragment.model_shape["condition"]["property"]
            filterable[label].append(prop)
    return NormalizedSubgraph(
        labels=labels,
        predicates=predicates,
        filterable_properties={
            label: tuple(dict.fromkeys(properties))
            for label, properties in filterable.items()
        },
        reporting_context="NewsArticle" in labels,
    )


def _compatible_relationship(fragment: Fragment, subgraph: NormalizedSubgraph) -> bool:
    piece_id = fragment.implications["relationship_ids"][0]
    piece = BY_ID[piece_id]
    labels = set(subgraph.labels)
    predicates = set(subgraph.predicates)
    return (
        piece.source_label.value in labels
        and piece.target_label.value in labels
        and {predicate.value for predicate in piece.predicates} <= predicates
    )


def candidate_fragments(subgraph: NormalizedSubgraph) -> tuple[Fragment, ...]:
    """Return only fragments whose full implications fit the narrowed subgraph."""

    labels = set(subgraph.labels)
    predicates = set(subgraph.predicates)
    fragments: list[Fragment] = []

    # Entity-only fragments preserve mention and shared-chunk cases. They do not
    # invent an ontology edge between an entity and stored reporting.
    fragments.extend(
        fragment
        for fragment in _entity_fragments()
        if fragment.model_shape["entity"] in labels
    )
    fragments.extend(
        fragment
        for fragment in all_relationship_fragments()
        if _compatible_relationship(fragment, subgraph)
    )
    fragments.extend(
        fragment
        for fragment in _filter_fragments()
        if fragment.model_shape["entity"] in labels
        and fragment.model_shape["condition"]["property"]
        in subgraph.filterable_properties[fragment.model_shape["entity"]]
    )
    for fragment in _aggregate_fragments():
        shape = fragment.model_shape
        if (
            shape["source_entity"] in labels
            and shape["target_entity"] in labels
            and set(shape["relationship"]) <= predicates
        ):
            fragments.append(fragment)
    return tuple(fragments)


def filter_prompt(fragment: Fragment) -> dict[str, Any] | None:
    """Ask whether a property condition exists, without assigning it to a role."""

    if not fragment.fragment_id.startswith("ANCHOR__"):
        return None
    shape = fragment.model_shape
    entity = shape["entity"]
    condition = shape["condition"]
    prop = condition["property"]
    comparison = condition["comparison"]
    field = f"{entity}.{prop}"

    if comparison == "date_gte":
        decision = (
            f"Does the question specify a date or time window that requires an inclusive "
            f"lower bound on {field}?"
        )
        meaning = f"The minimal query constrains {field} at or after a question-derived date."
    elif comparison == "date_lt":
        decision = (
            f"Does the question specify a date or time window that requires an exclusive "
            f"upper bound on {field}?"
        )
        meaning = f"The minimal query constrains {field} before a question-derived date."
    else:
        decision = f"Does the question specify a value that fixes or constrains {field}?"
        meaning = (
            f"The minimal query restricts {field} with the {comparison} comparison using "
            "a value stated in the question."
        )

    rules = [
        "Decide only whether this property condition exists; structural relationship selection is a separate decision.",
        "A named or otherwise explicit value counts whether the entity is returned or used to restrict the result.",
        "Do not infer a condition from schema availability alone.",
    ]
    if comparison in {"date_gte", "date_lt"}:
        rules.append(
            "A bounded calendar period such as July 2026 requires both an inclusive lower bound and an exclusive upper bound."
        )
    return {
        "decision": decision,
        "condition": {
            "entity": entity,
            "property": prop,
            "comparison": comparison,
            "value_source": "explicit wording in the natural-language question",
        },
        "meaning": meaning,
        "rules": rules,
    }


def filter_attachment_rules(
    fragments: Iterable[Fragment], selected_fragment_ids: Iterable[str]
) -> list[dict[str, str]]:
    """Describe compiler/composer-owned filter attachment after fragment selection."""

    by_id = {fragment.fragment_id: fragment for fragment in fragments}
    selected = [by_id[fragment_id] for fragment_id in selected_fragment_ids]
    role_counts: Counter[str] = Counter()
    for fragment in selected:
        incoming = Counter(fragment.implications.get("role_ids", ()))
        for role_id, count in incoming.items():
            role_counts[role_id] = max(role_counts[role_id], count)

    rules: list[dict[str, str]] = []
    for fragment in selected:
        if not fragment.fragment_id.startswith("ANCHOR__"):
            continue
        entity = fragment.model_shape["entity"]
        prop = fragment.model_shape["condition"]["property"]
        role_id = f"ROLE__{entity.upper()}"
        if entity == "NewsArticle":
            attachment = "the compiler-owned article role"
        elif role_counts[role_id] == 1:
            attachment = "the only selected role with this entity label"
        elif prop in {"name", "title"}:
            attachment = "the anchor role with this entity label; peer roles stay unrestricted"
        else:
            attachment = "the question-scoped role or roles resolved by the downstream composer"
        rules.append(
            {
                "filter_fragment_id": fragment.fragment_id,
                "entity": entity,
                "property": prop,
                "attachment": attachment,
            }
        )
    return rules


def pruning_audit(subgraph: NormalizedSubgraph, fragments: Iterable[Fragment]) -> dict[str, Any]:
    fragments = tuple(fragments)
    relationship_fragments = [
        fragment for fragment in fragments if "relationships" in fragment.model_shape
        or "relationship" in fragment.model_shape and "source_entity" in fragment.model_shape
    ]
    return {
        "candidate_count": len(fragments),
        "entity_context_count": sum(fragment.fragment_id.startswith("CONTEXT__") for fragment in fragments),
        "relationship_fragment_count": len(relationship_fragments),
        "filter_fragment_count": sum(fragment.fragment_id.startswith("ANCHOR__") for fragment in fragments),
        "aggregate_fragment_count": sum(fragment.fragment_id.startswith("COMPLETE__") for fragment in fragments),
        "predicate_family_rule": (
            "A relationship fragment survives only when both endpoints are selected and every predicate "
            "in that fragment is present. A family union therefore survives only when the filter selected "
            "the whole family; single family members remain competing alternatives."
        ),
        "reporting_context_rule": (
            "Article semantics may add one compiler-owned NewsArticle role. No selectable standalone "
            "NewsArticle context fragment or synthetic entity-to-article ontology relationship is added; "
            "reporting joins remain automatic."
        ),
        "repeated_peer_rule": (
            "Each surviving relationship keeps its single, repeated-source, and repeated-target variants. "
            "A peer variant implies both relationship occurrences, repeated roles, and distinctness."
        ),
    }
