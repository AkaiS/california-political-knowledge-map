"""Decide reporting intent after selection without shared request state."""

from knowledge_map.jev import jev_staged_selector as staged
from knowledge_map.prompts import load_prompt

GATE_THRESHOLD = 0.52
GATE_KEY = "relationship_free_reporting"
GATE_DECISION = load_prompt(
    "jev-staged/reporting-keyword-gate-gate-decision-01", version=1
)
GATE_CRITERIA = {
    "true": load_prompt(
        "jev-staged/reporting-keyword-gate-gate-criteria-01", version=1
    ),
    "false": load_prompt(
        "jev-staged/reporting-keyword-gate-gate-criteria-02", version=1
    ),
}


def select_pieces(client, question, schema_selection):
    result = staged.select_pieces(client, question, schema_selection)
    result["relationship_free_mode"] = "forbidden"
    output = result.get("output") or {}
    plan = result.get("refined_role_plan") or {}
    if not result["ok"] or output.get("relationship_ids") or plan.get("edges"):
        return result
    questions = {
        GATE_KEY: staged.Noul(instructions=GATE_DECISION, criteria=GATE_CRITERIA)
    }
    answers, stage = staged._call(
        client,
        GATE_KEY,
        {"question": question, "selected_semantic_role_plan": plan},
        questions,
        {key: value.model_dump(mode="json") for key, value in questions.items()},
    )
    stage["threshold"] = GATE_THRESHOLD
    if stage.get("error"):
        result.update(ok=False, output=None)
        result["normalization_errors"].append(
            "Reporting intent could not be determined."
        )
    elif answers[GATE_KEY]["noul"] >= GATE_THRESHOLD:
        result["relationship_free_mode"] = "shared_reporting"
    stage["relationship_free_mode"] = result["relationship_free_mode"]
    result["stages"].append(stage)
    for key in ("requests", "input_tokens", "output_tokens", "total_tokens"):
        result["usage"][key] = result["usage"].get(key, 0) + stage["usage"][key]
    return result
