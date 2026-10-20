"""Chat Evaluation Runs over authored Chat Session outputs, saved as Evaluation Reports."""

from __future__ import annotations

import asyncio
from pathlib import Path

from engine_runs import run_task
from test_retrieval import COVERAGE, coordinator

from knowledge_map.evaluation import LabelQuality
from knowledge_map.evaluation.tasks.chat import ChatFailure, ChatInput, ChatOutput
from knowledge_map.schemas.query_preparation import (
    DeclinedQuestion,
    QueryRewrite,
    QuestionAssessment,
)
from knowledge_map.schemas.retrieval import RetrievalAnswer

ALLOWED = QuestionAssessment(status="allowed")


def chat_input(case_id):
    return ChatInput(question=f"Who supported {case_id}?")


def answer(case_id, introduction):
    package = asyncio.run(
        coordinator().run(
            QueryRewrite(
                question=f"Who supported {case_id}?",
                relational=False,
                assessment=ALLOWED,
            ),
            coverage=COVERAGE,
            relevant_collection_ids=("reporting",),
        )
    )
    return RetrievalAnswer(evidence=package, introduction=introduction)


def answered(case_id, introduction="Read these articles first."):
    return (
        case_id,
        None,
        ChatOutput(
            question=f"Who supported {case_id}?",
            approval_mode="direct_question",
            assessment=ALLOWED,
            answer=answer(case_id, introduction),
            rendered_text="A rendered Source Guide.",
        ),
    )


def assessed(case_id, status, **fields):
    return (
        case_id,
        None,
        ChatOutput(
            question=f"Who supported {case_id}?",
            approval_mode="direct_question",
            assessment=QuestionAssessment(
                status=status, explanation="An explanation.", **fields
            ),
            rendered_text="An explanation.",
        ),
    )


def declined_in_preparation(case_id):
    """A historical approval run records only its question preparation."""

    return (
        case_id,
        None,
        ChatOutput(
            question=f"Who supported {case_id}?",
            preparation=DeclinedQuestion(message="Outside policy."),
        ),
    )


# The Chat Session failed after an allowed assessment, and kept its trail.
STAGE_FAILURE = (
    "AB 9",
    None,
    ChatOutput(
        question="Who supported AB 9?",
        approval_mode="direct_question",
        assessment=ALLOWED,
        failure=ChatFailure(
            stage="retrieval_and_guidance",
            kind="execution",
            exception_type="RuntimeError",
            diagnostic="Chat evaluation could not complete retrieval_and_guidance.",
        ),
    ),
)

FRAMEWORK_FAILURE = ("AB 10", None, RuntimeError("transport exhausted"))


def run_chat(directory: Path, cases) -> Path:
    """Run ``cases`` -- (id, expected, authored output) -- on an Unlabeled Set."""

    return run_task(
        directory,
        "chat",
        cases,
        task_input=chat_input,
        label_quality=LabelQuality.UNLABELED,
    )
