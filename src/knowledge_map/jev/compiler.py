"""Compile semantic wiring and add result/provenance hydration in code."""

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Literal

from knowledge_map.jev.catalog import Piece
from knowledge_map.jev.contracts import (
    SemanticWiring,
)
from knowledge_map.jev.topology import (
    Constraint,
    Inequality,
    NodeLabel,
    NodeVar,
    Predicate,
)
from knowledge_map.ontology import news

PARENT_LABEL = {NodeLabel.LABOR_UNION: "Organization", NodeLabel.PAC: "Organization"}


class SemanticCompileError(ValueError):
    pass


@dataclass(frozen=True)
class CompiledSemantic:
    cypher: str
    slots: tuple[str, ...]
    slot_descriptions: dict[str, str]
    binding_pattern: Any
    wiring: SemanticWiring
    evidence_rules: tuple[dict[str, Any], ...]


def _base(label: NodeLabel) -> str:
    return PARENT_LABEL.get(label, label.value)


def _match_labels(label: NodeLabel) -> str:
    parent = PARENT_LABEL.get(label)
    return f":{parent}:{label.value}" if parent else f":{label.value}"


def _compatible(actual: NodeLabel, expected: NodeLabel | None) -> bool:
    return expected is not None and actual == expected


def validate_wiring(
    wiring: SemanticWiring,
    grouped: dict[str, list[Piece]],
    *,
    relationship_free_mode: Literal["forbidden", "shared_reporting"] = "forbidden",
    allow_parent_distinct: bool = False,
) -> list[str]:
    roles = grouped["role"]
    relationships = grouped["relationship"]
    filters = grouped["filter"]
    constraints = grouped["role_constraint"]
    aggregates = grouped["aggregation"]
    errors: list[str] = []

    def role(index: int, context: str) -> Piece | None:
        if not 0 <= index < len(roles):
            errors.append(f"{context} role index {index} is out of range")
            return None
        return roles[index]

    seen_relationships: list[int] = []
    for item in wiring.triples:
        if not 0 <= item.relationship_index < len(relationships):
            errors.append(
                f"relationship index {item.relationship_index} is out of range"
            )
            continue
        seen_relationships.append(item.relationship_index)
        piece = relationships[item.relationship_index]
        source = role(item.source_role_index, "source")
        target = role(item.target_role_index, "target")
        if source and not (
            _compatible(source.node_label, piece.source_label)
            or (
                allow_parent_distinct
                and piece.source_label.value == _base(source.node_label)
            )
        ):
            errors.append(
                f"relationship {item.relationship_index} needs source {piece.source_label.value}"
            )
        if target and not (
            _compatible(target.node_label, piece.target_label)
            or (
                allow_parent_distinct
                and piece.target_label.value == _base(target.node_label)
            )
        ):
            errors.append(
                f"relationship {item.relationship_index} needs target {piece.target_label.value}"
            )
    if sorted(seen_relationships) != list(range(len(relationships))):
        errors.append("use every selected relationship occurrence exactly once")

    seen_filters: list[int] = []
    for item in wiring.filters:
        if not 0 <= item.filter_index < len(filters):
            errors.append(f"filter index {item.filter_index} is out of range")
            continue
        seen_filters.append(item.filter_index)
        selected_role = role(item.role_index, "filter")
        if (
            selected_role
            and selected_role.node_label != filters[item.filter_index].node_label
        ):
            errors.append(
                f"filter {item.filter_index} needs a {filters[item.filter_index].node_label.value} role"
            )
    if sorted(seen_filters) != list(range(len(filters))):
        errors.append("use every selected filter occurrence exactly once")

    seen_constraints: list[int] = []
    for item in wiring.distinct_roles:
        if not 0 <= item.constraint_index < len(constraints):
            errors.append(
                f"role constraint index {item.constraint_index} is out of range"
            )
            continue
        seen_constraints.append(item.constraint_index)
        left = role(item.left_role_index, "left distinct")
        right = role(item.right_role_index, "right distinct")
        expected = constraints[item.constraint_index].node_label
        if item.left_role_index == item.right_role_index:
            errors.append("a distinct-role constraint needs two role occurrences")
        if (
            left
            and left.node_label != expected
            and not (allow_parent_distinct and expected.value == _base(left.node_label))
        ):
            errors.append(
                f"role constraint {item.constraint_index} has the wrong left label"
            )
        if (
            right
            and right.node_label != expected
            and not (
                allow_parent_distinct and expected.value == _base(right.node_label)
            )
        ):
            errors.append(
                f"role constraint {item.constraint_index} has the wrong right label"
            )
    if sorted(seen_constraints) != list(range(len(constraints))):
        errors.append("use every selected role constraint occurrence exactly once")

    if aggregates:
        if len(aggregates) != 1 or wiring.aggregate is None:
            errors.append("use the selected aggregate exactly once")
        else:
            item = wiring.aggregate
            if item.aggregation_index != 0:
                errors.append("aggregate index is out of range")
            group = role(item.group_role_index, "aggregate group")
            count = role(item.count_role_index, "aggregate count")
            if group and group.node_label != aggregates[0].group_label:
                errors.append("aggregate group role has the wrong label")
            if count and count.node_label != aggregates[0].count_label:
                errors.append("aggregate count role has the wrong label")
    elif wiring.aggregate is not None:
        errors.append("do not invent an aggregate")

    if relationships:
        adjacency = {index: set() for index in range(len(roles))}
        used = set()
        for item in wiring.triples:
            if (
                item.source_role_index in adjacency
                and item.target_role_index in adjacency
            ):
                adjacency[item.source_role_index].add(item.target_role_index)
                adjacency[item.target_role_index].add(item.source_role_index)
                used.update((item.source_role_index, item.target_role_index))
        if used:
            reached = {next(iter(used))}
            frontier = list(reached)
            while frontier:
                current = frontier.pop()
                for neighbor in adjacency[current] - reached:
                    reached.add(neighbor)
                    frontier.append(neighbor)
            reporting_roles = {
                item.role_index
                for item in wiring.filters
                if item.role_index not in used
                and 0 <= item.role_index < len(roles)
                and roles[item.role_index].node_label == NodeLabel.NEWS_ARTICLE
            }
            if reached != set(range(len(roles))) - reporting_roles:
                errors.append(
                    "every selected role must belong to the connected semantic pattern"
                )
    else:
        if relationship_free_mode != "shared_reporting":
            errors.append(
                "relationship-free compilation is legal only for an explicit shared-reporting question"
            )
        article_count = sum(
            piece.node_label == NodeLabel.NEWS_ARTICLE for piece in roles
        )
        if article_count > 1:
            errors.append("role-only reporting supports at most one NewsArticle role")
        non_article_count = len(roles) - article_count
        if non_article_count < 1:
            errors.append(
                "role-only reporting needs at least one mentioned entity role"
            )
    return list(dict.fromkeys(errors))


def _semantic_relationship_properties(
    alias: str, predicates: tuple[Predicate, ...]
) -> str:
    names = sorted(
        {
            spec.name
            for predicate in predicates
            for spec in news.RELATIONSHIPS[predicate.value].properties
            if spec.name not in {"chunks", "articles"}
        }
        | {
            "needs_review"
            for predicate in predicates
            if news.RELATIONSHIPS[predicate.value].properties
        }
    )
    if not names:
        return "{}"
    return alias + "{" + ",".join(f".{name}" for name in names) + "}"


def compile_semantic(
    wiring: SemanticWiring,
    grouped: dict[str, list[Piece]],
    *,
    relationship_free_mode: Literal["forbidden", "shared_reporting"] = "forbidden",
    allow_parent_distinct: bool = False,
) -> CompiledSemantic:
    errors = validate_wiring(
        wiring,
        grouped,
        relationship_free_mode=relationship_free_mode,
        allow_parent_distinct=allow_parent_distinct,
    )
    if errors:
        raise SemanticCompileError("; ".join(errors))
    roles = grouped["role"]
    relationships = grouped["relationship"]
    filters = grouped["filter"]
    role_aliases = [f"role_{index}" for index in range(len(roles))]
    rel_aliases = [f"semantic_rel_{index}" for index in range(len(relationships))]
    semantic_indexes = {
        index
        for triple in wiring.triples
        for index in (triple.source_role_index, triple.target_role_index)
    }
    reporting_aliases = {
        alias
        for index, alias in enumerate(role_aliases)
        if wiring.triples
        and index not in semantic_indexes
        and roles[index].node_label == NodeLabel.NEWS_ARTICLE
    }

    constraints: list[Constraint] = []
    for index, item in enumerate(wiring.filters):
        piece = filters[item.filter_index]
        constraints.append(
            Constraint(
                variable=role_aliases[item.role_index],
                property=piece.property,
                operator=piece.operator,
                slot=f"parameter_{index}",
                description=piece.description,
            )
        )
    inequalities = [
        Inequality(
            left_variable=role_aliases[item.left_role_index],
            right_variable=role_aliases[item.right_role_index],
        )
        for item in wiring.distinct_roles
    ]
    binding_pattern = SimpleNamespace(
        nodes=[
            NodeVar(name=alias, label=piece.node_label)
            for alias, piece in zip(role_aliases, roles, strict=True)
        ],
        constraints=constraints,
        inequalities=inequalities,
        relationships=[
            {
                "source_variable": role_aliases[item.source_role_index],
                "predicates": [
                    predicate.value
                    for predicate in relationships[item.relationship_index].predicates
                ],
                "target_variable": role_aliases[item.target_role_index],
            }
            for item in wiring.triples
        ],
    )

    clauses: list[str] = []
    if wiring.triples:
        patterns = []
        for item in wiring.triples:
            piece = relationships[item.relationship_index]
            source = role_aliases[item.source_role_index]
            target = role_aliases[item.target_role_index]
            rel = rel_aliases[item.relationship_index]
            predicates = "|".join(predicate.value for predicate in piece.predicates)
            patterns.append(
                f"({source}{_match_labels(roles[item.source_role_index].node_label)})"
                f"-[{rel}:{predicates}]->"
                f"({target}{_match_labels(roles[item.target_role_index].node_label)})"
            )
        clauses.append("MATCH " + ",\n      ".join(patterns))
    else:
        clauses.append(
            "MATCH "
            + ",".join(
                f"({alias}{_match_labels(piece.node_label)})"
                for alias, piece in zip(role_aliases, roles, strict=True)
            )
        )

    def condition(constraint, variable=None):
        prop = f"{variable or constraint.variable}.{constraint.property.value}"
        value = f"${constraint.slot}"
        if constraint.operator.value == "eq":
            return f"{prop} = {value}"
        operator = ">=" if constraint.operator.value == "date_gte" else "<"
        return f"date(substring({prop},0,10)) {operator} date({value})"

    reporting_constraints = [
        constraint
        for constraint in constraints
        if constraint.variable in reporting_aliases
    ]
    where = [
        condition(constraint)
        for constraint in constraints
        if constraint.variable not in reporting_aliases
    ]
    where.extend(
        f"{item.left_variable}.id <> {item.right_variable}.id" for item in inequalities
    )
    if where:
        clauses.append("WHERE " + " AND ".join(where))

    if wiring.aggregate is not None:
        return _compile_aggregate(
            clauses,
            wiring,
            grouped,
            role_aliases,
            rel_aliases,
            binding_pattern,
            constraints,
        )

    carried = [
        *(alias for alias in role_aliases if alias not in reporting_aliases),
        *rel_aliases,
    ]
    evidence_rules: list[dict[str, Any]] = []
    if wiring.triples:
        by_relationship = {item.relationship_index: item for item in wiring.triples}
        for index, piece in enumerate(relationships):
            item = by_relationship[index]
            source = role_aliases[item.source_role_index]
            target = role_aliases[item.target_role_index]
            rel = rel_aliases[index]
            chunk = f"_chunk_{index}"
            article = f"_article_{index}"
            if piece.predicates == (Predicate.DISCUSSES_TOPIC,):
                clauses.append(f"MATCH ({source})-[:HAS_CHUNK]->({chunk}:Chunk)")
                mechanism = "article_owned"
            elif piece.predicates == (Predicate.ABOUT_TOPIC,):
                clauses.append(
                    f"UNWIND coalesce({rel}.articles,[]) AS _article_id_{index}"
                )
                clauses.append(
                    f"MATCH ({article}:NewsArticle {{id:_article_id_{index}}})-[:HAS_CHUNK]->({chunk}:Chunk)"
                )
                mechanism = "relationship_article_owned"
            else:
                clauses.append(f"UNWIND coalesce({rel}.chunks,[]) AS _chunk_id_{index}")
                clauses.append(
                    f"MATCH ({source})-[:MENTIONED_IN]->({chunk}:Chunk {{id:_chunk_id_{index}}})"
                )
                clauses.append(f"MATCH ({target})-[:MENTIONED_IN]->({chunk})")
                clauses.append(f"MATCH ({article}:NewsArticle)-[:HAS_CHUNK]->({chunk})")
                mechanism = "relationship_chunk_endpoint_intersection"
            article_expr = (
                source if piece.predicates == (Predicate.DISCUSSES_TOPIC,) else article
            )
            if reporting_constraints:
                clauses.append(
                    "WHERE "
                    + " AND ".join(
                        condition(constraint, article_expr)
                        for constraint in reporting_constraints
                    )
                )
            chunk_ids = f"_chunk_ids_{index}"
            article_ids = f"_article_ids_{index}"
            chunk_values = f"_chunk_values_{index}"
            article_values = f"_article_values_{index}"
            clauses.append(
                "WITH "
                + ",".join(
                    [
                        *carried,
                        f"collect(DISTINCT {chunk}.id) AS {chunk_ids}",
                        f"collect(DISTINCT {article_expr}.id) AS {article_ids}",
                        f"collect(DISTINCT {chunk}{{.id,.index,.text}}) AS {chunk_values}",
                        f"collect(DISTINCT properties({article_expr})) AS {article_values}",
                    ]
                )
            )
            carried.extend((chunk_ids, article_ids, chunk_values, article_values))
            evidence_rules.append(
                {
                    "relationship_index": index,
                    "mechanism": mechanism,
                    "independent_from_other_relationships": True,
                }
            )
    else:
        entity_indexes = [
            index
            for index, piece in enumerate(roles)
            if piece.node_label != NodeLabel.NEWS_ARTICLE
        ]
        article_indexes = [
            index
            for index, piece in enumerate(roles)
            if piece.node_label == NodeLabel.NEWS_ARTICLE
        ]
        chunk = "_role_chunk"
        article = (
            role_aliases[article_indexes[0]] if article_indexes else "_role_article"
        )
        first = entity_indexes[0]
        clauses.append(
            f"MATCH ({role_aliases[first]})-[:MENTIONED_IN]->({chunk}:Chunk)"
        )
        for index in entity_indexes[1:]:
            clauses.append(f"MATCH ({role_aliases[index]})-[:MENTIONED_IN]->({chunk})")
        clauses.append(f"MATCH ({article}:NewsArticle)-[:HAS_CHUNK]->({chunk})")
        clauses.append(
            "WITH "
            + ",".join(
                [
                    *role_aliases,
                    f"collect(DISTINCT {chunk}.id) AS _chunk_ids_0",
                    f"collect(DISTINCT {article}.id) AS _article_ids_0",
                    f"collect(DISTINCT {chunk}{{.id,.index,.text}}) AS _chunk_values_0",
                    f"collect(DISTINCT properties({article})) AS _article_values_0",
                ]
            )
        )
        carried.extend(
            ("_chunk_ids_0", "_article_ids_0", "_chunk_values_0", "_article_values_0")
        )
        evidence_rules.append(
            {
                "relationship_index": None,
                "mechanism": "deterministic_shared_role_context",
                "independent_from_other_relationships": True,
            }
        )

    fields = []
    for index, alias in enumerate(role_aliases):
        if alias in reporting_aliases:
            continue
        fields.extend(
            (
                f"{alias}.id AS role_{index}_id",
                f"properties({alias}) AS role_{index}_properties",
            )
        )
    for index, piece in enumerate(relationships):
        alias = rel_aliases[index]
        fields.extend(
            (
                f"type({alias}) AS semantic_relationship_{index}_relationship",
                f"{_semantic_relationship_properties(alias, piece.predicates)} AS semantic_relationship_{index}_properties",
                f"_article_ids_{index} AS semantic_relationship_{index}_article_ids",
            )
        )
    if not relationships:
        fields.append("_article_ids_0 AS role_context_article_ids")
    groups = ",".join(
        f"{{kind:'semantic_relationship_{index}',ids:_chunk_ids_{index}}}"
        for index in range(len(relationships) or 1)
    )
    details = ",".join(
        f"{{kind:'semantic_relationship_{index}',chunks:_chunk_values_{index},articles:_article_values_{index}}}"
        for index in range(len(relationships) or 1)
    )
    fields.extend(
        (f"[{groups}] AS evidence_groups", f"[{details}] AS hydrated_evidence")
    )
    clauses.append("RETURN DISTINCT " + ",\n       ".join(fields))
    return CompiledSemantic(
        cypher="\n".join(clauses),
        slots=tuple(constraint.slot for constraint in constraints),
        slot_descriptions={
            constraint.slot: constraint.description for constraint in constraints
        },
        binding_pattern=binding_pattern,
        wiring=wiring,
        evidence_rules=tuple(evidence_rules),
    )


def _compile_aggregate(
    clauses: list[str],
    wiring: SemanticWiring,
    grouped: dict[str, list[Piece]],
    role_aliases: list[str],
    rel_aliases: list[str],
    binding_pattern: Any,
    constraints: list[Constraint],
) -> CompiledSemantic:
    relationships = grouped["relationship"]
    if len(relationships) != 1 or relationships[0].predicates != (
        Predicate.DISCUSSES_TOPIC,
    ):
        raise SemanticCompileError(
            "the experiment's aggregate applies only to NewsArticle DISCUSSES_TOPIC PolicyArea"
        )
    aggregate = wiring.aggregate
    article = role_aliases[aggregate.count_role_index]
    group = role_aliases[aggregate.group_role_index]
    rel = rel_aliases[0]
    clauses.append(f"MATCH ({article})-[:HAS_CHUNK]->(_entry_candidate:Chunk)")
    clauses.append(
        f"WITH {group},{article},{rel},_entry_candidate ORDER BY _entry_candidate.index,_entry_candidate.id"
    )
    clauses.append(
        f"WITH {group},{article},{rel},head(collect(DISTINCT _entry_candidate)) AS _entry_chunk"
    )
    fields = [
        f"{group}.id AS role_{aggregate.group_role_index}_id",
        f"properties({group}) AS role_{aggregate.group_role_index}_properties",
        f"count(DISTINCT {article}.id) AS article_count",
        f"collect(DISTINCT {article}.id) AS article_ids",
        f"collect(DISTINCT properties({article})) AS article_properties",
        f"collect(DISTINCT {{kind:{article}.id,ids:[_entry_chunk.id]}}) AS evidence_groups",
        "collect(DISTINCT _entry_chunk{.id,.index,.text}) AS hydrated_chunks",
        f"type({rel}) AS semantic_relationship_0_relationship",
        f"{_semantic_relationship_properties(rel, relationships[0].predicates)} AS semantic_relationship_0_properties",
    ]
    clauses.append("RETURN " + ",\n       ".join(fields))
    return CompiledSemantic(
        cypher="\n".join(clauses),
        slots=tuple(constraint.slot for constraint in constraints),
        slot_descriptions={
            constraint.slot: constraint.description for constraint in constraints
        },
        binding_pattern=binding_pattern,
        wiring=wiring,
        evidence_rules=(
            {
                "relationship_index": 0,
                "mechanism": "article_owned_first_chunk_per_counted_article",
                "independent_from_other_relationships": True,
            },
        ),
    )
