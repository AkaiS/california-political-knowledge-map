"""Replace the reporting keyword gate with one post-selection Jev Noul."""

import json
import time


GATE_THRESHOLD = 0.52
GATE_KEY = "relationship_free_reporting"
GATE_DECISION = (
    "Does the question request stored reporting about the selected entities or "
    "shared reporting co-occurrence, rather than a recorded semantic claim "
    "relationship?"
)
GATE_CRITERIA = {
    "true": "The question requests a reporting lookup about the selected entities or shared reporting co-occurrence.",
    "false": "The question requests a semantic claim relationship, or does not specify a reporting relationship.",
}


def apply(runner, staged, fragments):
    original_selector = runner.select_pieces_with_staged_jev
    modes = {}

    def select_with_reporting_gate(client, question, schema_selection):
        modes.pop(question, None)
        result = original_selector(client, question, schema_selection)
        output = result.get("output") or {}
        plan = result.get("refined_role_plan") or {}
        if (
            not result.get("ok")
            or output.get("relationship_ids")
            or plan.get("edges")
        ):
            return result

        started = time.perf_counter()
        questions = {
            GATE_KEY: staged.Noul(
                instructions=GATE_DECISION,
                criteria=GATE_CRITERIA,
            )
        }
        captured = {
            key: value.model_dump(mode="json") for key, value in questions.items()
        }
        answers, stage = staged._call(
            client,
            "relationship_free_reporting",
            {"question": question, "selected_semantic_role_plan": plan},
            questions,
            captured,
        )
        stage["threshold"] = GATE_THRESHOLD
        modes[question] = "forbidden"
        if stage.get("error"):
            result["ok"] = False
            result["output"] = None
            result["normalization_errors"] = [
                *result.get("normalization_errors", []),
                f"Reporting gate failed: {stage['error']}",
            ]
        else:
            probability = answers[GATE_KEY]["noul"]
            result.setdefault("decisions", {})[GATE_KEY] = {"score": probability}
            if probability >= GATE_THRESHOLD:
                modes[question] = "shared_reporting"
        stage["relationship_free_mode"] = modes[question]
        result.setdefault("stages", []).append(stage)
        for key in ("requests", "input_tokens", "output_tokens", "total_tokens"):
            result["usage"][key] = (
                result["usage"].get(key, 0) + stage["usage"][key]
            )
        if stage.get("model") is not None:
            result["model"] = stage["model"]
        result["model_visible_prompt"] = json.dumps(
            {"stages": result["stages"]}, ensure_ascii=False
        )
        result["latency_ms"] = round(
            result.get("latency_ms", 0)
            + (time.perf_counter() - started) * 1000,
            1,
        )
        return result

    def relationship_free_mode(question):
        return modes.pop(question, "forbidden")

    runner.select_pieces_with_staged_jev = select_with_reporting_gate
    runner._relationship_free_mode = relationship_free_mode
    return {
        "variant": "reporting_keyword_gate",
        "mutation": "Replace only the lexical relationship-free reporting gate with one post-selection Jev Noul",
        "gate_decision": GATE_DECISION,
        "gate_criteria": GATE_CRITERIA,
        "gate_threshold": GATE_THRESHOLD,
        "gate_eligibility": "Successful selection with no semantic relationship IDs or role-plan edges",
        "failure_policy": "Forbidden on negative, missing, invalid, or failed decision; API errors fail the selector",
        "baseline_thresholds": [
            staged.STRUCTURE_THRESHOLD,
            staged.SUBTYPE_THRESHOLD,
            staged.PROPERTY_THRESHOLD,
        ],
    }
