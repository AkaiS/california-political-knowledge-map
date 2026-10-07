"""PROTOTYPE: batched Jev judgments over the compiler's semantic vocabulary."""

# Record service failures in the experiment instead of silently broadening schema.
# ruff: noqa: BLE001

from __future__ import annotations

import json
import math
import time
from typing import Any

from typesafe_sdk import Noul, NoulCriteria, TypeSafeClient

from knowledge_map.prototypes.atomic_deterministic_hydration.catalog import (
    CATALOG,
    SEMANTIC_LABELS,
    SEMANTIC_PREDICATES,
)
from knowledge_map.prototypes.atomic_deterministic_hydration.contracts import (
    SemanticSchemaSelection,
)

DEFAULT_THRESHOLD = 0.30

RELATIONSHIP_DEFINITIONS = {
    "DISCUSSES_TOPIC": "Connects a stored news article to the policy area it discusses.",
    "DECLARED_STANCE": "Connects a person or organization to a Bill or ballot proposition about which it has explicitly stated a position.",
    "ENDORSED": "Connects a person or organization to a ballot proposition or campaign it publicly backs.",
    "LOBBIED_FOR": "Connects an organization to a Bill it is recorded as lobbying in support of.",
    "LOBBIED_AGAINST": "Connects an organization to a Bill it is recorded as lobbying in opposition to.",
    "ABOUT_TOPIC": "Connects a Bill or ballot proposition to its policy area; this classifies the measure's subject.",
    "FUNDED": "Connects an organization to a campaign it is recorded as providing money to.",
    "CAMPAIGN_FOR": "Connects a campaign to the person or ballot proposition it targets. This identifies the measure or person associated with a funded campaign.",
    "VOTED_AYE": "Connects a person to a legislative event at which their recorded vote was affirmative. It is one possible outcome when retrieving a person's recorded vote.",
    "VOTED_NO": "Connects a person to a legislative event at which their recorded vote was negative. It is one possible outcome when retrieving a person's recorded vote.",
    "ABSTAINED": "Connects a person to a legislative event with an abstention or unrecorded vote. It is one possible outcome when retrieving a person's recorded vote.",
    "ACTION_ON": "Connects a legislative event, including a vote event, to the Bill that the event concerns.",
    "REFERRED_TO": "Connects a Bill to a legislative committee to which it was referred.",
}


def validate_threshold(value: float) -> float:
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError("schema threshold must be finite and between 0 and 1")
    return value


def _public_label(value: str) -> str:
    return "Article" if value == "NewsArticle" else value


def schema_candidates() -> dict[str, dict[str, Any]]:
    """Derive valid labels, relationship endpoints, and property pairs from code."""
    candidates = {
        f"label__{label.value}": {"kind": "label", "label": label.value}
        for label in SEMANTIC_LABELS
    }
    candidates["label__Politician"]["definition"] = (
        "An individual person. Politician is the graph's only person label; "
        "judge personhood, without needing to establish the person's political status."
    )
    for predicate in SEMANTIC_PREDICATES:
        endpoints = sorted(
            {
                (
                    _public_label(piece.source_label.value),
                    _public_label(piece.target_label.value),
                )
                for piece in CATALOG
                if piece.kind == "relationship" and predicate in piece.predicates
            }
        )
        candidates[f"relationship__{predicate.value}"] = {
            "kind": "relationship",
            "predicate": predicate.value,
            "definition": RELATIONSHIP_DEFINITIONS[predicate.value],
            "valid_endpoints": [list(pair) for pair in endpoints],
        }
    pairs = sorted(
        {
            (_public_label(piece.node_label.value), piece.property.value)
            for piece in CATALOG
            if piece.kind == "filter"
        }
    )
    for label, prop in pairs:
        candidates[f"property__{label}__{prop}"] = {
            "kind": "property",
            "label": label,
            "property": prop,
        }
        if label == "Politician":
            candidates[f"property__{label}__{prop}"]["definition"] = (
                "The individual's name, usable to restrict results to a named person."
            )
    return candidates


def build_request(
    question: str,
) -> tuple[dict[str, Any], dict[str, Noul], dict[str, Any]]:
    candidates = schema_candidates()
    state = {
        "question": question,
        "semantic_schema": list(candidates.values()),
        "selection_guidance": [
            "Keep semantic schema elements that could be needed to answer the question.",
            "Labels cover entities returned, anchors, and intermediate endpoints on a required path.",
            "Politician is the graph's person slot. Recognize individual people without inferring political status or graph membership.",
            "Organization covers general organizations; LaborUnion and PAC are specialized organization types.",
            "Bill is a legislative measure; Prop is a ballot proposition, not a Bill.",
            "A vote on a Bill uses a Politician vote relationship to LegislativeEvent and ACTION_ON to Bill.",
            "When a question asks what vote was recorded without specifying an outcome, all three possible vote relationships could be needed; do not predict the recorded outcome.",
            "Article is compiler-owned. Only its topic relationship and title/date filters are classified.",
            "Articles that discuss a policy area use DISCUSSES_TOPIC. Entity policy classification uses ABOUT_TOPIC.",
            "Stored reporting about an entity is automatic and does not imply a semantic claim relationship.",
            "A topic-related element is unnecessary unless it could participate in answering the question.",
            "Each judgment is independent; do not assume any other judgment's answer.",
        ],
    }
    questions = {}
    captured = {}
    for key, candidate in candidates.items():
        if candidate["kind"] == "label":
            decision = (
                (
                    "Could answering `question` require an individual person, "
                    "as a result, a named anchor, or an intermediate entity?"
                )
                if candidate["label"] == "Politician"
                else (
                    f"Could answering `question` require an entity of type {candidate['label']}, "
                    "as a result, question anchor, or intermediate entity?"
                )
            )
        elif candidate["kind"] == "relationship":
            decision = (
                f"Could answering `question` require the semantic relationship {candidate['predicate']} "
                "on a path connecting entities, including an intermediate relationship?"
            )
        else:
            decision = (
                (
                    "Does `question` specify an individual person's name that could "
                    "restrict results, including a named person used as a question anchor?"
                )
                if candidate["label"] == "Politician"
                else (
                    f"Does `question` specify a value or time window that could constrain "
                    f"{candidate['label']}.{candidate['property']}?"
                )
            )
        instructions = {"decision": decision, "candidate": candidate}
        criteria = NoulCriteria(
            true="This element could be needed by the semantic query described by the question.",
            false="This element is unrelated, merely topical, or unnecessary for answering the question.",
        )
        questions[key] = Noul(instructions=instructions, criteria=criteria)
        captured[key] = {
            "type": "noul",
            "instructions": instructions,
            "criteria": criteria,
        }
    return state, questions, captured


def normalize_decisions(
    candidates: dict[str, dict[str, Any]], scores: dict[str, float], threshold: float
) -> tuple[SemanticSchemaSelection, dict[str, Any]]:
    """Retain all valid endpoint alternatives without selecting semantic roles."""
    validate_threshold(threshold)
    if set(scores) != set(candidates):
        raise ValueError("schema decisions must exactly cover the candidate vocabulary")
    if any(
        not math.isfinite(score) or not 0 <= score <= 1 for score in scores.values()
    ):
        raise ValueError("schema probabilities must be finite and between 0 and 1")
    selected = [key for key in candidates if scores[key] >= threshold]
    labels = {
        candidates[key]["label"]
        for key in selected
        if candidates[key]["kind"] == "label"
    }
    direct_labels = sorted(labels)
    relationships = []
    properties: dict[str, list[str]] = {}
    reasons: dict[str, list[str]] = {}
    article_reasons = []

    def retain(label: str, reason: str) -> None:
        if label == "Article":
            article_reasons.append(reason)
        else:
            labels.add(label)
            reasons.setdefault(label, []).append(reason)

    for key in selected:
        candidate = candidates[key]
        if candidate["kind"] == "relationship":
            predicate = candidate["predicate"]
            relationships.append(predicate)
            for source, target in candidate["valid_endpoints"]:
                retain(source, f"endpoint of {predicate}")
                retain(target, f"endpoint of {predicate}")
        elif candidate["kind"] == "property":
            label = candidate["label"]
            properties.setdefault(label, []).append(candidate["property"])
            retain(label, f"selected property {label}.{candidate['property']}")
    selection = SemanticSchemaSelection(
        labels=sorted(labels),
        relationships=sorted(relationships),
        filter_properties={
            label: sorted(values) for label, values in sorted(properties.items())
        },
        rationale="Jev schema probabilities thresholded with deterministic endpoint and property closure.",
    )
    closure = {
        "direct_label_selections": direct_labels,
        "added_labels": [
            {"label": label, "reasons": sorted(set(reasons[label]))}
            for label in sorted(labels - set(direct_labels))
        ],
        "compiler_owned_article_required": bool(article_reasons),
        "compiler_owned_article_reasons": sorted(set(article_reasons)),
        "policy": "Retain every catalog endpoint alternative of a selected predicate and every selected property's label.",
    }
    return selection, {"selected_candidate_ids": selected, "closure": closure}


def narrow_schema(
    client: TypeSafeClient, question: str, *, threshold: float = DEFAULT_THRESHOLD
) -> dict[str, Any]:
    """Make one schema request; missing or invalid answers stop this backend."""
    validate_threshold(threshold)
    state, questions, captured = build_request(question)
    candidates = schema_candidates()
    result = {
        "ok": False,
        "backend": "jev",
        "threshold": threshold,
        "threshold_status": "experimental, uncalibrated",
        "model": None,
        "output": None,
        "decisions": {},
        "normalization_errors": [],
        "selected_candidate_ids": [],
        "closure": None,
        "candidate_count": len(candidates),
        "usage": {"requests": 1},
        "retry_count": None,
        "model_visible_prompt": json.dumps(
            {"state": state, "questions": captured},
            ensure_ascii=False,
            separators=(",", ":"),
        ),
    }
    started = time.perf_counter()
    try:
        response = client.system_one(state=state, questions=questions)
        result["model"] = response.model
        input_tokens = response.usage.input_tokens or 0
        output_tokens = response.usage.output_tokens or 0
        result["usage"].update(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
        )
        scores = {}
        for key, candidate in candidates.items():
            answer = response.nouls.get(key)
            if answer is None:
                result["normalization_errors"].append(
                    f"missing Jev schema answer for {key}"
                )
                continue
            score = float(answer.noul)
            result["decisions"][key] = {
                "candidate": candidate,
                "score": score,
                "selected_by_threshold": score >= threshold,
            }
            scores[key] = score
        if not result["normalization_errors"]:
            selection, audit = normalize_decisions(candidates, scores, threshold)
            result.update(ok=True, output=selection.model_dump(mode="json"), **audit)
    except Exception as error:
        result["error"] = {"type": type(error).__name__, "message": str(error)}
        result["normalization_errors"].append("Jev schema call or normalization failed")
    result["latency_ms"] = round((time.perf_counter() - started) * 1000, 1)
    return result
