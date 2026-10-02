import logging
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from knowledge_map.adapters.sqlite_db import DEFAULT_DB_PATH
from knowledge_map.schemas import ModelDeployment
from knowledge_map.utils.agents import create_agent
from knowledge_map.utils.models import DEFAULT_LOCAL_CHAT_MODEL, get_chat_model

from knowledge_map.prompts import load_prompt

logger = logging.getLogger(__name__)

# 1. Structured Pydantic output model
class RelevanceClassification(BaseModel):
    classification: Literal["RELEVANT", "IRRELEVANT"] = Field(
        ...,
        description="Whether the article is RELEVANT or IRRELEVANT to California politics"
    )

RELEVANCE_AGENT_INSTRUCTIONS = (
    load_prompt("relevance/instructions", version=1)
)

def get_relevance_agent_prompt(
    title: str,
    body: str,
    positive_examples: List[Dict[str, Any]],
    negative_examples: List[Dict[str, Any]]
) -> str:
    """Compiles the prompt containing examples and instructions for the classification task."""
    prompt_lines = []
    
    if positive_examples or negative_examples:
        prompt_lines.extend([
            load_prompt("relevance/example-instructions", version=1),
            ""
        ])
        
    if positive_examples:
        prompt_lines.append(load_prompt("relevance/positive-examples-heading", version=1))
        for ex in positive_examples:
            prompt_lines.extend(
                [
                    load_prompt("relevance/article-title", version=1).format(
                        title=ex.get("title", "")
                    ),
                    load_prompt("relevance/article-content", version=1).format(
                        content=ex.get("content", "")
                    ),
                    load_prompt("relevance/positive-classification", version=1),
                    "---",
                ]
            )
        prompt_lines.append("")

    if negative_examples:
        prompt_lines.append(load_prompt("relevance/negative-examples-heading", version=1))
        for ex in negative_examples:
            prompt_lines.extend(
                [
                    load_prompt("relevance/article-title", version=1).format(
                        title=ex.get("title", "")
                    ),
                    load_prompt("relevance/article-content", version=1).format(
                        content=ex.get("content", "")
                    ),
                    load_prompt("relevance/negative-classification", version=1),
                    "---",
                ]
            )
        prompt_lines.append("")

    prompt_lines.extend([
        load_prompt("relevance/target-heading", version=1),
        load_prompt("relevance/article-title", version=1).format(title=title),
        load_prompt("relevance/target-body", version=1).format(body=body),
        "",
        load_prompt("relevance/classification-request", version=1)
    ])

    return "\n".join(prompt_lines)


def get_relevance_agent(
    deployment: ModelDeployment | None = None,
    *,
    defer_check: bool = True,
) -> Agent:
    """Build the Relevance Filter agent from one explicit deployment.

    Callers without a deployment use the configured local chat deployment.
    """

    model = (
        get_chat_model(deployment)
        if deployment is not None
        else get_chat_model(DEFAULT_LOCAL_CHAT_MODEL)
    )
    return create_agent(
        model,
        name="relevance_classifier",
        output_type=RelevanceClassification,
        instructions=RELEVANCE_AGENT_INSTRUCTIONS,
        defer_model_check=defer_check,
    )


async def classify_article_with_llm(
    title: str,
    body: str,
    db_path: str = DEFAULT_DB_PATH,
    agent: Optional[Agent] = None,
    *,
    deployment: ModelDeployment | None = None,
) -> RelevanceClassification:
    """
    Asynchronously queries the database for gold standard examples,
    then runs the Pydantic AI classifier agent on the article.
    """
    if agent is None:
        agent = get_relevance_agent(deployment)

    # Fetch examples from database
    try:
        from knowledge_map.adapters.sqlite_db import get_gold_standard_examples
        db_examples = get_gold_standard_examples(db_path)
    except Exception:
        db_examples = []

    positives = [e for e in db_examples if e.get("relevance_status") == "RELEVANT"]
    negatives = [e for e in db_examples if e.get("relevance_status") == "IRRELEVANT"]

    if not positives or not negatives:
        logger.warning("Running relevance classifier agent without examples: No human-labeled examples available in the database.")

    prompt = get_relevance_agent_prompt(title, body, positives[:3], negatives[:3])
    result = await agent.run(prompt)
    return result.output
