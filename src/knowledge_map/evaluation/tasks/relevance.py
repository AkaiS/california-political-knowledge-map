"""The Relevance Filter as an evaluated task.

The Gold Set for this task is `evals/gold/relevance.yaml`. Its cases come
from the 92 rows in `scraped_html_cache` the author already labeled by
hand, which is why `collect_candidates` exists and why it writes the
author's own label as the expected output rather than leaving it blank.
"""

from __future__ import annotations

import json
import os
import sqlite3
from typing import Any, Literal, NamedTuple

from dotenv import load_dotenv
from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_evals.evaluators import Evaluator, EvaluatorContext

from knowledge_map.adapters.sqlite_db import DEFAULT_DB_PATH
from knowledge_map.core.relevance_agent import (
    RELEVANCE_AGENT_INSTRUCTIONS,
    RelevanceClassification,
    get_relevance_agent_prompt,
)
from knowledge_map.utils.models import get_chat_model

from .registry import EvaluationTask, register

FALLBACK_MODEL = "32k-gemma-e4b"


def default_model() -> str:
    """The model the Relevance Filter runs in production, per `.env`.

    Comparing two models is the point of a run, so the model is named
    explicitly rather than resolved from the environment at call time —
    `get_chat_model` lets `OLLAMA_MODEL_RELEVANCE` override its
    argument, which would silently ignore `--model`. This reads the same
    variable once, to supply the default the run then records.

    `load_dotenv` is called because this runs at import, before anything
    else has read the file. Without it the fallback wins and a run with no
    `--model` records a model name that is in no configuration file --
    which is what happened until `tasks.coreference` began loading the
    file first, leaving this correct only by import order.
    """

    load_dotenv()
    return (
        os.environ.get("OLLAMA_MODEL_RELEVANCE")
        or os.environ.get("OLLAMA_MODEL")
        or FALLBACK_MODEL
    )


class RelevanceInput(BaseModel):
    """One article as the Relevance Filter sees it."""

    url: str
    headline: str
    description: str = ""


class RelevanceExpectation(BaseModel):
    """The author's own judgment on one article."""

    classification: Literal["RELEVANT", "IRRELEVANT"]


class RelevanceMetadata(BaseModel):
    publication_id: str | None = None
    label_source: str | None = None


def build_task(model: str, gold_set: Any) -> Any:
    """Return the callable one case is run through, bound to ``model``.

    Few-shot examples come from the Gold Set's own `training` split, not
    from `get_gold_standard_examples`. That function selects three
    human-labeled rows per class straight out of `scraped_html_cache`,
    which is where every case in this Gold Set came from: using it during
    a run puts up to six of the run's own cases, with their labels, into
    the prompt scoring them.
    """
    agent = Agent(
        get_chat_model(model),
        output_type=RelevanceClassification,
        instructions=RELEVANCE_AGENT_INSTRUCTIONS,
        defer_model_check=True,
    )
    positives, negatives = _few_shot_examples(gold_set)

    async def classify(case_input: RelevanceInput) -> RelevanceExpectation:
        prompt = get_relevance_agent_prompt(
            title=case_input.headline,
            body=case_input.description,
            positive_examples=positives,
            negative_examples=negatives,
        )
        result = await agent.run(prompt)
        return RelevanceExpectation(classification=result.output.classification)

    return classify


def _few_shot_examples(gold_set: Any) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Draw up to three examples per class from the `training` split only.

    A case the author put in `calibration` or `held-out` is reserved from
    exactly this, so a Gold Set with no `training` cases few-shots with
    nothing, which is the correct answer rather than a reason to fall
    back to the database.
    """
    from knowledge_map.evaluation import EvaluationSplit

    training = gold_set.split(EvaluationSplit.TRAINING)
    by_label: dict[str, list[dict[str, str]]] = {"RELEVANT": [], "IRRELEVANT": []}
    for case in training:
        label = case.expected_output.classification
        if len(by_label[label]) < 3:
            by_label[label].append(
                {"title": case.task_input.headline, "content": case.task_input.description}
            )
    return by_label["RELEVANT"], by_label["IRRELEVANT"]


class MatchesTheAuthorsLabel(Evaluator):
    """The Relevance Filter agreed with the human label on this article."""

    def evaluate(self, ctx: EvaluatorContext) -> bool:
        return ctx.output.classification == ctx.expected_output.classification


class RecalledARelevantArticle(Evaluator):
    """A `RELEVANT` article was not dropped.

    Scored separately from agreement because dropping a relevant article
    costs more than admitting an irrelevant one: the graph never sees it.
    Cases the author labeled `IRRELEVANT` are not scored by this evaluator.
    """

    def evaluate(self, ctx: EvaluatorContext) -> bool | None:
        if ctx.expected_output.classification != "RELEVANT":
            return None
        return ctx.output.classification == "RELEVANT"


class CollectedCandidates(NamedTuple):
    """What `collect_candidates` found, and what it could not use."""

    cases: list[dict[str, Any]]
    skipped_urls: tuple[str, ...]
    """Human-labeled rows with no headline in either column or metadata."""


def collect_candidates(db_path: str = DEFAULT_DB_PATH) -> CollectedCandidates:
    """Read every human-labeled article out of `scraped_html_cache`.

    The author labeled these while running the pipeline; this reads them
    back as cases rather than asking for the judgment a second time. The
    `id` is the URL, which is stable, so re-running this updates a member
    instead of appending a second one.

    A row whose `headline` column is null falls back to the headline in
    `raw_metadata_json`, and is reported as skipped when neither has one.
    Most such rows are `IRRELEVANT`, which is the label this Gold Set has
    least of, so losing them silently would bias the population.
    """
    connection = sqlite3.connect(db_path)
    try:
        rows = connection.execute(
            """
            SELECT url, headline, description, relevance_status,
                   publication_id, relevance_label_source, raw_metadata_json
            FROM scraped_html_cache
            WHERE relevance_label_source = 'HUMAN'
              AND relevance_status IN ('RELEVANT', 'IRRELEVANT')
            ORDER BY url
            """
        ).fetchall()
    finally:
        connection.close()

    cases: list[dict[str, Any]] = []
    skipped: list[str] = []
    for url, headline, description, status, publication_id, label_source, metadata_json in rows:
        metadata = _raw_metadata(metadata_json)
        headline = headline or metadata.get("headline")
        if not headline:
            skipped.append(url)
            continue
        cases.append(
            {
                "id": url,
                "description": headline,
                "split": "held-out",
                "task_input": {
                    "url": url,
                    "headline": headline,
                    "description": description or metadata.get("description") or "",
                },
                "expected_output": {"classification": status},
                "metadata": {
                    "publication_id": publication_id,
                    "label_source": label_source,
                },
            }
        )
    return CollectedCandidates(cases=cases, skipped_urls=tuple(skipped))


def _raw_metadata(metadata_json: str | None) -> dict[str, Any]:
    try:
        parsed = json.loads(metadata_json or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


RELEVANCE_TASK = register(
    EvaluationTask(
        name="relevance",
        input_type=RelevanceInput,
        output_type=RelevanceExpectation,
        metadata_type=RelevanceMetadata,
        build=build_task,
        evaluators=(MatchesTheAuthorsLabel(), RecalledARelevantArticle()),
        default_model=default_model(),
        collect=collect_candidates,
    )
)
