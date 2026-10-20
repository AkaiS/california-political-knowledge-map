"""Relevance Evaluation Runs over authored outputs, saved as Evaluation Reports."""

from __future__ import annotations

from pathlib import Path

from engine_runs import run_task

from knowledge_map.evaluation import LabelQuality
from knowledge_map.evaluation.tasks.relevance import (
    RelevanceExpectation,
    RelevanceInput,
)

RELEVANT = RelevanceExpectation(classification="RELEVANT")
IRRELEVANT = RelevanceExpectation(classification="IRRELEVANT")

CONFUSION_CASES = [
    ("tp-1", RELEVANT, RELEVANT),
    ("tp-2", RELEVANT, RELEVANT),
    ("fp", IRRELEVANT, RELEVANT),
    ("fn", RELEVANT, IRRELEVANT),
    ("both-negative", IRRELEVANT, IRRELEVANT),
]


def run_relevance(directory: Path, cases) -> Path:
    """Run ``cases`` -- (id, expected label, authored output) -- through ``run_task``."""

    return run_task(
        directory,
        "relevance",
        cases,
        task_input=lambda case_id: RelevanceInput(url=case_id, headline=case_id),
        label_quality=LabelQuality.GOLD,
    )
