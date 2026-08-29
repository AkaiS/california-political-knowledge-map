import logging
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from knowledge_map.adapters.sqlite_db import DEFAULT_DB_PATH
from knowledge_map.schemas import ModelDeployment
from knowledge_map.utils.models import get_chat_model

logger = logging.getLogger(__name__)

# 1. Structured Pydantic output model
class RelevanceClassification(BaseModel):
    classification: Literal["RELEVANT", "IRRELEVANT"] = Field(
        ...,
        description="Whether the article is RELEVANT or IRRELEVANT to California politics"
    )

RELEVANCE_AGENT_INSTRUCTIONS = (
    "You are a California Politics Relevance Classifier.\n"
    "Your job is to determine whether a news article is relevant to California politics, policy, elections, lobbying, or state/local governance.\n\n"
    "Examine the title and body of the target article and classify it as either 'RELEVANT' or 'IRRELEVANT'\n"
    "If example classifications are provided, use them to guide your decision."
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
            "Instructions: Classify the target article below based on the examples provided.",
            ""
        ])
        
    if positive_examples:
        prompt_lines.append("--- Examples of RELEVANT California Politics Articles ---")
        for ex in positive_examples:
            prompt_lines.extend([
                f"Title: {ex.get('title', '')}",
                f"Content: {ex.get('content', '')}",
                "Classification: RELEVANT",
                "---"
            ])
        prompt_lines.append("")

    if negative_examples:
        prompt_lines.append("--- Examples of IRRELEVANT Articles ---")
        for ex in negative_examples:
            prompt_lines.extend([
                f"Title: {ex.get('title', '')}",
                f"Content: {ex.get('content', '')}",
                "Classification: IRRELEVANT",
                "---"
            ])
        prompt_lines.append("")

    prompt_lines.extend([
        "--- Target Article to Classify ---",
        f"Title: {title}",
        f"Body: {body}",
        "",
        "Determine if the Target Article is RELEVANT or IRRELEVANT."
    ])

    return "\n".join(prompt_lines)


def get_relevance_agent(
    deployment: ModelDeployment | None = None,
    *,
    defer_check: bool = True,
) -> Agent:
    """Build the Relevance Filter agent from one explicit deployment.

    Legacy callers without a deployment retain the shared global model
    override, but a supplied deployment cannot be replaced by an environment
    model alias.
    """

    model = (
        get_chat_model(deployment)
        if deployment is not None
        else get_chat_model("32k-gemma-e4b", allow_env_override=True)
    )
    return Agent(
        model,
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
