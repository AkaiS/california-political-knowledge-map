"""Offline contract checks using synthetic selections and SDK-shaped responses."""

import copy
import importlib.util
import json
import time
from pathlib import Path
from types import SimpleNamespace

from knowledge_map.prototypes.atomic_deterministic_hydration import (
    jev_staged_selector as staged,
)


MODULE_PATH = Path(__file__).with_name("reporting_keyword_gate.py")
spec = importlib.util.spec_from_file_location("reporting_keyword_gate", MODULE_PATH)
variant = importlib.util.module_from_spec(spec)
spec.loader.exec_module(variant)


class Answer(dict):
    def model_dump(self, **kwargs):
        return dict(self)


class Fake:
    def __init__(self, probability=0.52, error=False, missing=False, wrong=False):
        self.probability = probability
        self.error = error
        self.missing = missing
        self.wrong = wrong
        self.calls = []

    def system_one(self, **request):
        self.calls.append(request)
        time.sleep(0.005)
        if self.error:
            raise RuntimeError("synthetic API failure")
        answers = {}
        if not self.missing:
            answers[variant.GATE_KEY] = Answer(
                type="choice" if self.wrong else "noul",
                noul=self.probability,
            )
        return SimpleNamespace(
            answers=answers,
            model="synthetic-sdk-model",
            usage=SimpleNamespace(input_tokens=21, output_tokens=7),
        )


def selection():
    return {
        "ok": True,
        "output": {"role_ids": ["ROLE__ORGANIZATION"], "relationship_ids": []},
        "refined_role_plan": {
            "roles": [{"label": "Organization", "occurrence": 0}],
            "edges": [],
            "distinct": [],
        },
        "usage": {
            "requests": 2,
            "input_tokens": 100,
            "output_tokens": 20,
            "total_tokens": 120,
        },
        "model": "synthetic-baseline",
        "latency_ms": 8.0,
        "stages": [],
        "decisions": {},
        "normalization_errors": [],
        "model_visible_prompt": "synthetic-baseline",
        "filter_attachment_rules": [],
    }


def setup(result):
    runner = SimpleNamespace(
        select_pieces_with_staged_jev=lambda *args: copy.deepcopy(result),
        _relationship_free_mode=lambda *args: "baseline-keyword-mode",
    )
    structural_prompt = staged.structural_prompt
    thresholds = (
        staged.STRUCTURE_THRESHOLD,
        staged.SUBTYPE_THRESHOLD,
        staged.PROPERTY_THRESHOLD,
    )
    metadata = variant.apply(runner, staged, None)
    assert staged.structural_prompt is structural_prompt
    assert thresholds == (
        staged.STRUCTURE_THRESHOLD,
        staged.SUBTYPE_THRESHOLD,
        staged.PROPERTY_THRESHOLD,
    )
    return runner, metadata


def main():
    checks = 0
    question = "synthetic gate input"
    for probability, expected_mode in (
        (0.52, "shared_reporting"),
        (0.519, "forbidden"),
        (0.0, "forbidden"),
        (1.0, "shared_reporting"),
    ):
        original = selection()
        runner, metadata = setup(original)
        fake = Fake(probability)
        result = runner.select_pieces_with_staged_jev(fake, question, None)
        assert result["ok"]
        assert result["output"] == original["output"]
        assert len(fake.calls) == 1
        request = fake.calls[0]
        assert request["state"] == {
            "question": question,
            "selected_semantic_role_plan": original["refined_role_plan"],
        }
        assert len(request["questions"]) == 1
        data = request["questions"][variant.GATE_KEY].model_dump(mode="json")
        assert data["type"] == "noul"
        assert data["instructions"] == variant.GATE_DECISION
        assert data["criteria"] == variant.GATE_CRITERIA
        assert result["usage"] == {
            "requests": 3,
            "input_tokens": 121,
            "output_tokens": 27,
            "total_tokens": 148,
        }
        stage = result["stages"][-1]
        assert stage["state"] == request["state"]
        assert stage["questions"][variant.GATE_KEY] == data
        assert stage["decisions"][variant.GATE_KEY]["noul"] == probability
        assert result["latency_ms"] >= original["latency_ms"] + stage["latency_ms"] - 0.2
        assert json.loads(result["model_visible_prompt"])["stages"] == result["stages"]
        assert runner._relationship_free_mode(question) == expected_mode
        assert runner._relationship_free_mode(question) == "forbidden"
        assert runner._relationship_free_mode("uncached synthetic input") == "forbidden"
        checks += 1

    for bypass in ("failed", "relationship_ids", "plan_edges"):
        original = selection()
        if bypass == "failed":
            original.update(ok=False, output=None)
        elif bypass == "relationship_ids":
            original["output"]["relationship_ids"] = ["synthetic-semantic-edge"]
        else:
            original["refined_role_plan"]["edges"] = [{"piece_id": "synthetic-semantic-edge"}]
        runner, _ = setup(original)
        fake = Fake()
        result = runner.select_pieces_with_staged_jev(fake, question, None)
        assert result == original
        assert not fake.calls
        assert runner._relationship_free_mode(question) == "forbidden"
        checks += 1

    for fake in (
        Fake(error=True),
        Fake(missing=True),
        Fake(wrong=True),
        Fake(float("nan")),
    ):
        runner, _ = setup(selection())
        result = runner.select_pieces_with_staged_jev(fake, question, None)
        assert len(fake.calls) == 1
        assert not result["ok"] and result["output"] is None
        assert result["normalization_errors"]
        assert result["stages"][-1]["error"]
        assert result["usage"]["requests"] == 3
        assert runner._relationship_free_mode(question) == "forbidden"
        checks += 1

    original = selection()
    runner, _ = setup(original)
    runner.select_pieces_with_staged_jev(Fake(), question, None)
    original.update(ok=False, output=None)
    fake = Fake()
    runner.select_pieces_with_staged_jev(fake, question, None)
    assert not fake.calls
    assert runner._relationship_free_mode(question) == "forbidden"
    checks += 1

    print(json.dumps({"offline_checks_passed": checks, "metadata": metadata}, indent=2))


if __name__ == "__main__":
    main()
