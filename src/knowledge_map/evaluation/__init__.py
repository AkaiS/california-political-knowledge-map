"""Evaluation over Gold Sets authored as files, versioned by git (ADR 0017)."""

from .engine import build_dataset, run_gold_set
from .gold_set import (
    EvaluationCase,
    EvaluationGoldSet,
    EvaluationSplit,
    gold_set_path,
    load_gold_set,
)
from .report_file import report_path, run_commit, trace_url, write_report

__all__ = [
    "EvaluationCase",
    "EvaluationGoldSet",
    "EvaluationSplit",
    "build_dataset",
    "gold_set_path",
    "load_gold_set",
    "report_path",
    "run_commit",
    "run_gold_set",
    "trace_url",
    "write_report",
]
