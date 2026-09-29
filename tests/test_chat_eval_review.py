"""Human case reviews remain attached to the selected report."""

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "review_chat_eval.py"
SPEC = importlib.util.spec_from_file_location("review_chat_eval", SCRIPT)
assert SPEC and SPEC.loader
review_server = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(review_server)


def test_review_file_preserves_case_verdict_and_note(tmp_path):
    path = tmp_path / "reviews.json"
    reviews = {
        "case-1": {
            "verdict": "fail",
            "note": "Citation does not support the claim.",
        }
    }

    review_server.save_reviews(path, reviews)

    assert review_server.load_reviews(path) == reviews
    assert json.loads(path.read_text()) == reviews
    assert not list(tmp_path.glob(".reviews.json.*"))


def test_reviewer_rejects_non_chat_report(tmp_path):
    path = tmp_path / "report.json"
    path.write_text(json.dumps({"task": "extraction", "report": {"cases": []}}))

    with pytest.raises(ValueError, match="chat evaluation report"):
        review_server.load_report(path)
