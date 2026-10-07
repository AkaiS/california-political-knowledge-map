"""Staged role planning, subtype restriction, then attached properties."""

# ruff: noqa: BLE001
from __future__ import annotations

import json
import math
import time
from collections import Counter
from typing import Any

from typesafe_sdk import Choice, Noul, TypeSafeClient

from knowledge_map.jev.catalog import (
    BY_ID,
    CATALOG,
)
from knowledge_map.jev.contracts import (
    PieceSelection,
    SemanticSchemaSelection,
)
from knowledge_map.jev.expansion import (
    _expand,
)
from knowledge_map.jev.filtered_fragments import (
    candidate_fragments,
    filter_prompt,
    normalize_schema,
    pruning_audit,
)
from knowledge_map.jev.jev_schema_filter import (
    RELATIONSHIP_DEFINITIONS,
)
from knowledge_map.prompts import load_prompt

STRUCTURE_THRESHOLD = 0.52
SUBTYPE_THRESHOLD = 0.80
PROPERTY_THRESHOLD = 0.52
PARENT = {"PAC": "Organization", "LaborUnion": "Organization"}
PROMPT_REVISION = "separate-role-requested-category-campaign-target-v1"


class SelectionAbstention(ValueError):
    """An uncertain requested scope must not turn into a broader query."""


def parent_schema(schema: SemanticSchemaSelection) -> SemanticSchemaSelection:
    data = schema.model_dump(mode="json")
    data["labels"] = sorted({PARENT.get(label, label) for label in data["labels"]})
    return SemanticSchemaSelection.model_validate(data)


def parent_role_prompt(fragment):
    label = fragment.model_shape["entity"]
    entity = (
        load_prompt("jev-staged/jev-staged-selector-parent-role-prompt-01", version=1)
        if label == "Politician"
        else load_prompt(
            "jev-staged/jev-staged-selector-parent-role-prompt-02", version=1
        ).format(value_0=label)
    )
    return {
        "decision": load_prompt(
            "jev-staged/jev-staged-selector-parent-role-prompt-03", version=1
        ).format(value_0=entity),
        "parent_entity": label,
        "rules": [
            load_prompt(
                "jev-staged/jev-staged-selector-parent-role-prompt-04", version=1
            ),
            load_prompt(
                "jev-staged/jev-staged-selector-parent-role-prompt-05", version=1
            ),
            load_prompt(
                "jev-staged/jev-staged-selector-parent-role-prompt-06", version=1
            ),
            load_prompt(
                "jev-staged/jev-staged-selector-parent-role-prompt-07", version=1
            ),
            load_prompt(
                "jev-staged/jev-staged-selector-parent-role-prompt-08", version=1
            ),
            load_prompt(
                "jev-staged/jev-staged-selector-parent-role-prompt-09", version=1
            ),
        ],
    }


def structural_prompt(fragment):
    if fragment.fragment_id.startswith("CONTEXT__"):
        return parent_role_prompt(fragment)
    prompt = fragment.prompt()
    pieces = [BY_ID[pid] for pid in fragment.implications.get("relationship_ids", ())]
    if any("CAMPAIGN_FOR" in [p.value for p in piece.predicates] for piece in pieces):
        prompt["target_alternatives"] = {
            "Campaign -> Politician": load_prompt(
                "jev-staged/jev-staged-selector-structural-prompt-01", version=1
            ),
            "Campaign -> Prop": load_prompt(
                "jev-staged/jev-staged-selector-structural-prompt-02", version=1
            ),
        }
        prompt["rules"].extend(
            [
                load_prompt(
                    "jev-staged/jev-staged-selector-structural-prompt-03", version=1
                ),
                load_prompt(
                    "jev-staged/jev-staged-selector-structural-prompt-04", version=1
                ),
                load_prompt(
                    "jev-staged/jev-staged-selector-structural-prompt-05", version=1
                ),
            ]
        )
    return prompt


def make_role_plan(fragments, selected_ids):
    """Preserve original maximum-count sharing while distinguishing peer occurrences."""
    selected = [
        fragment for fragment in fragments if fragment.fragment_id in selected_ids
    ]
    counts = Counter()
    for fragment in selected:
        incoming = Counter(fragment.implications.get("role_ids", ()))
        for role_id, count in incoming.items():
            counts[role_id] = max(counts[role_id], count)
    needs_article = any(
        BY_ID[pid].source_label.value == "NewsArticle"
        or BY_ID[pid].target_label.value == "NewsArticle"
        for fragment in selected
        for pid in fragment.implications.get("relationship_ids", ())
    )
    roles = [
        {
            "role_id": role_id,
            "parent_label": BY_ID[role_id].node_label.value,
            "label": BY_ID[role_id].node_label.value,
            "occurrence": occurrence,
            "purposes": [],
        }
        for role_id, count in sorted(counts.items())
        for occurrence in range(count)
    ]
    if needs_article:
        roles.insert(
            0,
            {
                "role_id": "COMPILER__ARTICLE_ROLE",
                "parent_label": "NewsArticle",
                "label": "NewsArticle",
                "occurrence": 0,
                "purposes": ["compiler-owned topic article"],
            },
        )

    def find(label, occurrence=0):
        return next(
            i
            for i, role in enumerate(roles)
            if role["parent_label"] == label and role["occurrence"] == occurrence
        )

    edges, distinct = [], []
    for fragment in selected:
        rel_ids = fragment.implications.get("relationship_ids", ())
        for occurrence, pid in enumerate(rel_ids):
            piece = BY_ID[pid]
            source = find(
                piece.source_label.value,
                occurrence if fragment.variant == "peer_source" else 0,
            )
            target = find(
                piece.target_label.value,
                occurrence if fragment.variant == "peer_target" else 0,
            )
            if not any(
                e["piece_id"] == pid and e["source"] == source and e["target"] == target
                for e in edges
            ):
                edges.append(
                    {
                        "piece_id": pid,
                        "source": source,
                        "target": target,
                        "fragment_id": fragment.fragment_id,
                    }
                )
            for side, idx in (("source", source), ("target", target)):
                purpose = {
                    "side": side,
                    "predicates": [p.value for p in piece.predicates],
                    "opposite_label": roles[target if side == "source" else source][
                        "parent_label"
                    ],
                    "peer_status": ("anchor" if occurrence == 0 else "different peer")
                    if fragment.variant == f"peer_{side}"
                    else "single or shared",
                }
                if purpose not in roles[idx]["purposes"]:
                    roles[idx]["purposes"].append(purpose)
        for pid in fragment.implications.get("role_constraint_ids", ()):
            label = BY_ID[pid].node_label.value
            candidate = {
                "piece_id": pid,
                "left": find(label, 0),
                "right": find(label, 1),
            }
            if candidate not in distinct:
                distinct.append(candidate)
        if not rel_ids:
            for pid in fragment.implications.get("role_ids", ()):
                role = roles[find(BY_ID[pid].node_label.value)]
                role["purposes"].append(
                    {
                        "context": "entity returned or named anchor in automatic stored reporting"
                    }
                )
    return roles, edges, distinct


def mapped_piece(kind, roles, *, edge=None, piece=None):
    if kind == "relationship":
        original = BY_ID[edge["piece_id"]]
        matched = next(
            (
                p
                for p in CATALOG
                if p.kind == kind
                and p.predicates == original.predicates
                and p.source_label.value == roles[edge["source"]]["label"]
                and p.target_label.value == roles[edge["target"]]["label"]
            ),
            None,
        )
        if matched is not None:
            return matched
        if len(original.predicates) > 1 and all(
            expected.value == PARENT.get(roles[index]["label"], roles[index]["label"])
            for expected, index in (
                (original.source_label, edge["source"]),
                (original.target_label, edge["target"]),
            )
        ):
            edge["mapping_note"] = (
                "Catalog predicate union retained with compiler-checked parent compatibility; refined role supplies subtype restriction."
            )
            return original
        raise ValueError("No catalog relationship matches refined role endpoints")
    return next(
        p
        for p in CATALOG
        if p.kind == "filter"
        and p.node_label.value == roles[piece["role"]]["label"]
        and p.property == piece["piece"].property
        and p.operator == piece["piece"].operator
    )


def _call(client, stage, state, questions, captured):
    started = time.perf_counter()
    audit = {
        "name": stage,
        "state": state,
        "questions": captured,
        "decisions": {},
        "model": None,
        "usage": {
            "requests": 1,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
        },
    }
    try:
        response = client.system_one(state=state, questions=questions)
        audit["model"] = response.model
        audit["usage"].update(
            input_tokens=response.usage.input_tokens or 0,
            output_tokens=response.usage.output_tokens or 0,
        )
        audit["usage"]["total_tokens"] = (
            audit["usage"]["input_tokens"] + audit["usage"]["output_tokens"]
        )
        for key, question in captured.items():
            answer = response.answers.get(key)
            if answer is None:
                raise ValueError(f"Missing {stage} answer {key}")
            data = answer.model_dump(mode="json")
            audit["decisions"][key] = data
            if data["type"] != question["type"]:
                raise ValueError(f"Wrong answer type for {key}")
            probabilities = (
                [data["noul"]]
                if data["type"] == "noul"
                else list(data["probabilities"].values())
            )
            if not all(math.isfinite(p) and 0 <= p <= 1 for p in probabilities):
                raise ValueError(f"Invalid probability for {key}")
            if data["type"] == "choice" and (
                set(data["probabilities"]) != set(question["criteria"])
                or data["choice"] not in question["criteria"]
            ):
                raise ValueError(f"Invalid Choice options for {key}")
    except Exception as error:
        audit["error"] = f"{type(error).__name__}: {error}"
    audit["latency_ms"] = round((time.perf_counter() - started) * 1000, 1)
    return audit["decisions"], audit


def select_pieces(
    client: TypeSafeClient, question: str, schema_selection: SemanticSchemaSelection
) -> dict[str, Any]:
    stages, decisions, selected_filters = [], {}, []
    abstention = None
    started = time.perf_counter()
    subgraph = normalize_schema(parent_schema(schema_selection).model_dump(mode="json"))
    all_fragments = candidate_fragments(subgraph)
    structural = tuple(
        f for f in all_fragments if not f.fragment_id.startswith("ANCHOR__")
    )
    base_state = {
        "question": question,
        "relationship_definitions": RELATIONSHIP_DEFINITIONS,
        "entity_definitions": {
            "Politician": load_prompt(
                "jev-staged/jev-staged-selector-select-pieces-01", version=1
            ),
            "Organization": load_prompt(
                "jev-staged/jev-staged-selector-select-pieces-02", version=1
            ),
        },
        "rules": [
            load_prompt("jev-staged/jev-staged-selector-select-pieces-03", version=1),
            load_prompt("jev-staged/jev-staged-selector-select-pieces-04", version=1),
            load_prompt("jev-staged/jev-staged-selector-select-pieces-05", version=1),
            load_prompt("jev-staged/jev-staged-selector-select-pieces-06", version=1),
        ],
    }
    try:
        questions, captured = {}, {}
        for f in structural:
            prompt = structural_prompt(f)
            questions[f.fragment_id] = Noul(
                instructions=prompt,
                criteria={
                    "true": load_prompt(
                        "jev-staged/jev-staged-selector-select-pieces-08", version=1
                    ),
                    "false": load_prompt(
                        "jev-staged/jev-staged-selector-select-pieces-09", version=1
                    ),
                },
            )
            captured[f.fragment_id] = questions[f.fragment_id].model_dump(mode="json")
        scores, stage = _call(
            client,
            "parent_structure",
            {**base_state, "available_schema": subgraph.public()},
            questions,
            captured,
        )
        stages.append(stage)
        if stage.get("error"):
            raise ValueError(stage["error"])
        decisions.update(
            {key: {"score": answer["noul"]} for key, answer in scores.items()}
        )
        expanded = _expand(
            structural, {key: value["score"] for key, value in decisions.items()}
        )
        selected_ids = expanded["selected_fragment_ids"]
        roles, edges, distinct = make_role_plan(structural, selected_ids)
        parent_plan = json.loads(
            json.dumps({"roles": roles, "edges": edges, "distinct": distinct})
        )
        questions, captured = {}, {}
        for i, role in enumerate(roles):
            if role["parent_label"] != "Organization":
                continue
            key = f"scope_{i}"
            questions[key] = Choice(
                instructions={
                    "decision": load_prompt(
                        "jev-staged/jev-staged-selector-select-pieces-10", version=1
                    ),
                    "role_index": i,
                    "role": role,
                    "rules": [
                        load_prompt(
                            "jev-staged/jev-staged-selector-select-pieces-19", version=1
                        ),
                        load_prompt(
                            "jev-staged/jev-staged-selector-select-pieces-20", version=1
                        ),
                        load_prompt(
                            "jev-staged/jev-staged-selector-select-pieces-21", version=1
                        ),
                        load_prompt(
                            "jev-staged/jev-staged-selector-select-pieces-22", version=1
                        ),
                        load_prompt(
                            "jev-staged/jev-staged-selector-select-pieces-23", version=1
                        ),
                    ],
                },
                criteria={
                    "unrestricted": load_prompt(
                        "jev-staged/jev-staged-selector-select-pieces-11", version=1
                    ),
                    "PAC": load_prompt(
                        "jev-staged/jev-staged-selector-select-pieces-12", version=1
                    ),
                    "LaborUnion": load_prompt(
                        "jev-staged/jev-staged-selector-select-pieces-13", version=1
                    ),
                    "unclear": load_prompt(
                        "jev-staged/jev-staged-selector-select-pieces-14", version=1
                    ),
                },
            )
            captured[key] = questions[key].model_dump(mode="json")
        if questions:
            scopes, stage = _call(
                client,
                "role_subtypes",
                {**base_state, "selected_parent_role_plan": parent_plan},
                questions,
                captured,
            )
            stages.append(stage)
            if stage.get("error"):
                raise ValueError(stage["error"])
            for key, answer in scopes.items():
                i = int(key.split("_")[1])
                chosen = answer["choice"]
                roles[i]["scope_decision"] = answer
                probability = answer["probabilities"][chosen]
                if chosen == "unclear" or probability < SUBTYPE_THRESHOLD:
                    abstention = {
                        "stage": "role_subtypes",
                        "role_index": i,
                        "choice": chosen,
                        "probability": probability,
                        "required_probability": SUBTYPE_THRESHOLD,
                        "reason": "Requested category is uncertain; query stopped rather than broadening its scope.",
                    }
                    raise SelectionAbstention(abstention["reason"])
                if chosen in PARENT:
                    roles[i]["label"] = chosen
                    roles[i]["role_id"] = f"ROLE__{chosen.upper()}"
        # Publication filters may attach only to the one compiler-owned article role.
        article_available = "NewsArticle" in subgraph.labels
        property_roles = roles.copy()
        if article_available and not any(r["label"] == "NewsArticle" for r in roles):
            property_roles.append(
                {
                    "role_id": "COMPILER__ARTICLE_ROLE",
                    "parent_label": "NewsArticle",
                    "label": "NewsArticle",
                    "occurrence": 0,
                    "purposes": [
                        load_prompt(
                            "jev-staged/jev-staged-selector-select-pieces-15", version=1
                        )
                    ],
                }
            )
        questions, captured, property_candidates = {}, {}, {}
        for i, role in enumerate(property_roles):
            for f in all_fragments:
                if (
                    not f.fragment_id.startswith("ANCHOR__")
                    or f.model_shape["entity"] != role["parent_label"]
                ):
                    continue
                piece = BY_ID[f.implications["filter_ids"][0]]
                key = f"property_{i}_{piece.piece_id}"
                prompt = filter_prompt(f)
                prompt["role_index"] = i
                prompt["selected_role"] = role
                prompt["rules"].extend(
                    [
                        load_prompt(
                            "jev-staged/jev-staged-selector-select-pieces-16", version=1
                        ),
                        load_prompt(
                            "jev-staged/jev-staged-selector-select-pieces-17", version=1
                        ),
                        load_prompt(
                            "jev-staged/jev-staged-selector-select-pieces-18", version=1
                        ),
                    ]
                )
                questions[key] = Noul(
                    instructions=prompt,
                    criteria={
                        "true": load_prompt(
                            "jev-staged/jev-staged-selector-select-pieces-24", version=1
                        ),
                        "false": load_prompt(
                            "jev-staged/jev-staged-selector-select-pieces-25", version=1
                        ),
                    },
                )
                captured[key] = questions[key].model_dump(mode="json")
                property_candidates[key] = {
                    "role": i,
                    "piece": piece,
                    "fragment_id": f.fragment_id,
                }
        if questions:
            props, stage = _call(
                client,
                "role_properties",
                {
                    **base_state,
                    "refined_role_plan": {
                        "roles": property_roles,
                        "edges": edges,
                        "distinct": distinct,
                    },
                },
                questions,
                captured,
            )
            stages.append(stage)
            if stage.get("error"):
                raise ValueError(stage["error"])
            for key, answer in props.items():
                decisions[key] = {"score": answer["noul"]}
                if answer["noul"] >= PROPERTY_THRESHOLD:
                    selected_filters.append(property_candidates[key])
        article_selected = any(p["role"] == len(roles) for p in selected_filters)
        if article_selected:
            roles.append(property_roles[-1])
        output = {
            field: []
            for field in (
                "role_ids",
                "relationship_ids",
                "filter_ids",
                "role_constraint_ids",
                "aggregation_ids",
            )
        }
        output["role_ids"] = [
            r["role_id"] for r in roles if r["label"] != "NewsArticle"
        ]
        output["relationship_ids"] = [
            mapped_piece("relationship", roles, edge=e).piece_id for e in edges
        ]
        output["filter_ids"] = [
            mapped_piece("filter", roles, piece=p).piece_id for p in selected_filters
        ]
        output["role_constraint_ids"] = [d["piece_id"] for d in distinct]
        output["aggregation_ids"] = expanded["selection"]["aggregation_ids"]
        output = PieceSelection.model_validate(output).model_dump(mode="json")
        # _resolve_selection always inserts Article at index zero. Preserve all other occurrence order.
        index_map = {
            i: (
                0
                if role["label"] == "NewsArticle"
                else sum(r["label"] != "NewsArticle" for r in roles[:i])
                + int(any(r["label"] == "NewsArticle" for r in roles))
            )
            for i, role in enumerate(roles)
        }
        attachment = [
            {
                "instruction": load_prompt(
                    "jev-staged/jev-staged-selector-select-pieces-07", version=1
                ),
                "role_plan": roles,
                "triples": [
                    {
                        "relationship_index": i,
                        "source_role_index": index_map[e["source"]],
                        "target_role_index": index_map[e["target"]],
                    }
                    for i, e in enumerate(edges)
                ],
                "filters": [
                    {"filter_index": i, "role_index": index_map[p["role"]]}
                    for i, p in enumerate(selected_filters)
                ],
                "distinct_roles": [
                    {
                        "constraint_index": i,
                        "left_role_index": index_map[d["left"]],
                        "right_role_index": index_map[d["right"]],
                    }
                    for i, d in enumerate(distinct)
                ],
            }
        ]
        errors = []
    except Exception as error:
        output, errors, attachment, selected_ids, roles, parent_plan = (
            None,
            [f"{type(error).__name__}: {error}"],
            [],
            [],
            [],
            None,
        )
    usage = {
        key: sum(s["usage"][key] for s in stages)
        for key in ("requests", "input_tokens", "output_tokens", "total_tokens")
    }
    return {
        "ok": output is not None,
        "prompt_revision": PROMPT_REVISION,
        "abstention": abstention,
        "output": output,
        "normalization_errors": errors,
        "model": stages[-1]["model"] if stages else None,
        "decisions": decisions,
        "usage": usage,
        "latency_ms": round((time.perf_counter() - started) * 1000, 1),
        "model_visible_prompt": json.dumps({"stages": stages}, ensure_ascii=False),
        "stages": stages,
        "parent_role_plan": parent_plan,
        "refined_roles": roles,
        "refined_role_plan": {
            "roles": roles,
            "edges": edges if "edges" in locals() else [],
            "distinct": distinct if "distinct" in locals() else [],
        },
        "pruning": {
            **pruning_audit(subgraph, structural),
            "structural_candidate_count": len(structural),
            "subtype_question_count": sum(
                len(stage["questions"])
                for stage in stages
                if stage["name"] == "role_subtypes"
            ),
            "property_candidate_count": len(property_candidates)
            if "property_candidates" in locals()
            else 0,
        },
        "threshold": STRUCTURE_THRESHOLD,
        "subtype_threshold": SUBTYPE_THRESHOLD,
        "property_threshold": PROPERTY_THRESHOLD,
        "selected_fragment_ids": selected_ids,
        "filter_attachment_rules": attachment,
    }
