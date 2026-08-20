"""The Gold Set file is the authored artifact; these guard what it promises."""

from __future__ import annotations

import json
from datetime import UTC
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError
from pydantic_evals.evaluators import Evaluator, EvaluatorContext

from knowledge_map.evaluation import (
    EvaluationSplit,
    load_gold_set,
    report_path,
    run_gold_set,
    write_report,
)


class RelevanceInput(BaseModel):
    headline: str


class RelevanceLabel(BaseModel):
    relevant: bool


GOLD_SET_YAML = """
task: relevance
description: Hand-labeled headlines for the Relevance Filter.
cases:
  - id: sb-1047-veto
    description: A bill veto is California political news.
    split: held-out
    task_input:
      headline: Newsom vetoes SB 1047
    expected_output:
      relevant: true
  - id: dodgers-trade
    description: Sports is not California political news.
    split: training
    task_input:
      headline: Dodgers trade for a reliever
    expected_output:
      relevant: false
"""


@pytest.fixture
def gold_set_file(tmp_path: Path) -> Path:
    path = tmp_path / "relevance.yaml"
    path.write_text(GOLD_SET_YAML)
    return path


def load(path: Path):
    return load_gold_set(
        path, input_type=RelevanceInput, output_type=RelevanceLabel
    )


def test_a_gold_set_file_validates_against_the_task_types(gold_set_file: Path) -> None:
    gold_set = load(gold_set_file)

    assert gold_set.task == "relevance"
    assert tuple(case.id for case in gold_set.cases) == ("sb-1047-veto", "dodgers-trade")
    assert gold_set.cases[0].task_input == RelevanceInput(headline="Newsom vetoes SB 1047")
    assert gold_set.cases[0].expected_output == RelevanceLabel(relevant=True)


def test_a_case_typo_is_caught_when_the_file_is_read(tmp_path: Path) -> None:
    path = tmp_path / "relevance.yaml"
    path.write_text(GOLD_SET_YAML.replace("headline: Newsom vetoes SB 1047", "headlin: x"))

    with pytest.raises(ValidationError):
        load(path)


def test_a_gold_set_cannot_repeat_a_case_id(tmp_path: Path) -> None:
    path = tmp_path / "relevance.yaml"
    path.write_text(GOLD_SET_YAML.replace("dodgers-trade", "sb-1047-veto"))

    with pytest.raises(ValidationError, match="cannot repeat a case id"):
        load(path)


def test_split_selects_only_the_cases_the_author_assigned(gold_set_file: Path) -> None:
    gold_set = load(gold_set_file)

    held_out = gold_set.split(EvaluationSplit.HELD_OUT)

    assert tuple(case.id for case in held_out) == ("sb-1047-veto",)


def test_running_one_split_reports_the_authored_case_ids(gold_set_file: Path) -> None:
    gold_set = load(gold_set_file)

    report = run_gold_set(
        gold_set,
        task=lambda case_input: RelevanceLabel(relevant=True),
        evaluators=[MatchesExpectedOutput()],
        split=EvaluationSplit.HELD_OUT,
    )

    assert [case.name for case in report.cases] == ["sb-1047-veto"]
    assert report.cases[0].assertions["MatchesExpectedOutput"].value is True


def test_running_a_split_with_no_cases_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "relevance.yaml"
    path.write_text(GOLD_SET_YAML.replace("split: held-out", "split: training"))

    with pytest.raises(ValueError, match="no cases in the held-out split"):
        run_gold_set(
            load(path),
            task=lambda case_input: RelevanceLabel(relevant=True),
            evaluators=[MatchesExpectedOutput()],
            split=EvaluationSplit.HELD_OUT,
        )


def test_a_written_report_carries_the_commit_and_model_it_ran_at(
    gold_set_file: Path, tmp_path: Path
) -> None:
    gold_set = load(gold_set_file)
    report = run_gold_set(
        gold_set,
        task=lambda case_input: RelevanceLabel(relevant=True),
        evaluators=[MatchesExpectedOutput()],
    )

    path = write_report(
        report,
        task="relevance",
        model="claude-sonnet-5",
        gold_set_path=gold_set_file,
        root=tmp_path / "reports",
    )
    document = json.loads(path.read_text())

    assert path.parent.name == "relevance"
    assert document["model"] == "claude-sonnet-5"
    assert document["commit"]
    assert document["gold_set"] == str(gold_set_file)
    assert {case["name"] for case in document["report"]["cases"]} == {
        "sb-1047-veto",
        "dodgers-trade",
    }


def test_a_report_filename_separates_runs_of_the_same_task() -> None:
    from datetime import datetime

    ran_at = datetime(2026, 8, 19, 14, 30, tzinfo=UTC)

    first = report_path("relevance", model="claude-opus-5", ran_at=ran_at)
    second = report_path("relevance", model="claude-haiku-4-5", ran_at=ran_at)

    assert first != second
    assert first.parent == second.parent


class MatchesExpectedOutput(Evaluator):
    def evaluate(self, ctx: EvaluatorContext) -> bool:
        return ctx.output == ctx.expected_output


def test_collected_relevance_candidates_carry_the_url_as_the_case_id(tmp_path: Path) -> None:
    """Collection is idempotent because the id is the URL, not a row number."""
    import sqlite3

    from knowledge_map.evaluation.tasks.relevance import collect_candidates

    db_path = tmp_path / "document_store.db"
    connection = sqlite3.connect(db_path)
    connection.execute(
        """
        CREATE TABLE scraped_html_cache (
            url TEXT PRIMARY KEY, publication_id TEXT, headline TEXT,
            description TEXT, relevance_status TEXT, relevance_label_source TEXT,
            raw_metadata_json TEXT
        )
        """
    )
    connection.executemany(
        "INSERT INTO scraped_html_cache VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            ("u/1", "calmatters", "Newsom vetoes SB 1047", "d", "RELEVANT", "HUMAN", None),
            ("u/2", "calmatters", None, None, "IRRELEVANT", "HUMAN",
             '{"headline": "Pacific Catch opens", "description": "restaurants"}'),
            ("u/3", "calmatters", None, None, "IRRELEVANT", "HUMAN", None),
            ("u/4", "calmatters", "Machine labeled", "d", "RELEVANT", "LLM", None),
        ],
    )
    connection.commit()
    connection.close()

    collected = collect_candidates(str(db_path))

    assert [case["id"] for case in collected.cases] == ["u/1", "u/2"]
    assert collected.cases[1]["task_input"]["headline"] == "Pacific Catch opens"
    assert collected.skipped_urls == ("u/3",)
