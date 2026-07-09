from typing import Literal, Optional, List, Dict, Any
from pydantic import BaseModel, Field
from pydantic_ai import Agent

from knowledge_map.utils.models import get_ollama_model
from knowledge_map.adapters.sqlite_db import DEFAULT_DB_PATH

# 1. Structured Pydantic output model
class RelevanceClassification(BaseModel):
    classification: Literal["RELEVANT", "IRRELEVANT"] = Field(
        ...,
        description="Whether the article is RELEVANT or IRRELEVANT to California politics"
    )
    rationale: str = Field(
        ...,
        description="A concise rationale/explanation for the classification decision"
    )

# 2. Static Fallback Examples
STATIC_POSITIVE_EXAMPLES = [
    {
        "title": "Governor Signs Landmark California Housing Reform Bill",
        "content": "SACRAMENTO — Governor Gavin Newsom today signed a major legislative package aimed at streamlining housing approvals and boosting development across California. The bills, sponsored by key state senators, target zoning restrictions and local planning delays to address the state's ongoing affordability crisis.",
        "relevance_status": "RELEVANT",
        "rationale": "Discusses the California Governor signing state legislative bills concerning housing policy, which is a major area of state politics and policy."
    },
    {
        "title": "San Francisco Mayoral Candidates Clash in First Public Debate",
        "content": "SAN FRANCISCO — The race for San Francisco Mayor heated up last night as incumbent and challengers debated homelessness, public transit budgets, and police reform. Candidate speeches focused on local board decisions and upcoming ballot measures.",
        "relevance_status": "RELEVANT",
        "rationale": "Focuses on local municipal elections (San Francisco mayoral race), candidates, debate topics, and local ballot measures."
    },
    {
        "title": "Tech Lobbyists Invest Millions to Influence Sacramento Climate Regulations",
        "content": "Lobbying disclosures filed in Sacramento reveal that major technology coalitions spent record amounts last quarter. The lobbying efforts targeted assembly members debating new carbon disclosure requirements for large corporations operating in California.",
        "relevance_status": "RELEVANT",
        "rationale": "Covers lobbying efforts, political influence spending, and state assembly legislative debates in Sacramento."
    }
]

STATIC_NEGATIVE_EXAMPLES = [
    {
        "title": "The Best Sourdough Bakeries in the San Francisco Bay Area",
        "content": "If you are looking for the perfect crispy crust and airy crumb, here is a list of the top ten bakeries in the SF Bay Area. We review local spots and their fermentation techniques.",
        "relevance_status": "IRRELEVANT",
        "rationale": "The article is a lifestyle and food guide about bakeries, which is not related to California politics or policy."
    },
    {
        "title": "Los Angeles High School Football Championship Ends in Thrilling Overtime",
        "content": "The local high school football playoffs concluded on Friday with a dramatic victory. The winning touchdown in overtime sealed the regional championship before a sold-out local stadium crowd.",
        "relevance_status": "IRRELEVANT",
        "rationale": "The article is about local high school sports, which does not involve California political figures, lobbying, or state policy."
    },
    {
        "title": "Congress Debates Federal Trade Policy in Washington D.C.",
        "content": "WASHINGTON — Members of Congress clashed on the House floor today over a proposed federal tariff package on international imports. The debate centered on national economic impacts and trade relations with key foreign partners.",
        "relevance_status": "IRRELEVANT",
        "rationale": "Focuses entirely on federal trade policy and national congressional debates in Washington D.C. with no specific connection to California politics or state/local governance."
    }
]

RELEVANCE_AGENT_INSTRUCTIONS = (
    "You are a California Politics Relevance Classifier.\n"
    "Your job is to determine whether a news article is relevant to California politics, policy, elections, lobbying, or state/local governance.\n\n"
    "To help you, we have provided positive and negative examples of classification decisions with rationales.\n"
    "Examine the title and body of the target article and classify it as either 'RELEVANT' or 'IRRELEVANT', along with a concise rationale."
)

def get_relevance_agent_prompt(
    title: str,
    body: str,
    positive_examples: List[Dict[str, Any]],
    negative_examples: List[Dict[str, Any]]
) -> str:
    """Compiles the prompt containing examples and instructions for the classification task."""
    prompt_lines = [
        "Instructions: Classify the target article below based on the examples provided.",
        "",
        "--- Examples of RELEVANT California Politics Articles ---"
    ]
    for ex in positive_examples:
        prompt_lines.extend([
            f"Title: {ex.get('title', '')}",
            f"Content: {ex.get('content', '')}",
            "Classification: RELEVANT",
            f"Rationale: {ex.get('rationale', 'Matches California politics and policy.')}",
            "---"
        ])
        
    prompt_lines.append("")
    prompt_lines.append("--- Examples of IRRELEVANT Articles ---")
    for ex in negative_examples:
        prompt_lines.extend([
            f"Title: {ex.get('title', '')}",
            f"Content: {ex.get('content', '')}",
            "Classification: IRRELEVANT",
            f"Rationale: {ex.get('rationale', 'Not related to California politics or policy.')}",
            "---"
        ])

    prompt_lines.extend([
        "",
        "--- Target Article to Classify ---",
        f"Title: {title}",
        f"Body: {body}",
        "",
        "Determine if the Target Article is RELEVANT or IRRELEVANT and provide your rationale."
    ])

    return "\n".join(prompt_lines)


async def classify_article_with_llm(
    title: str,
    body: str,
    db_path: str = DEFAULT_DB_PATH,
    agent: Optional[Agent] = None
) -> RelevanceClassification:
    """
    Asynchronously queries the database for gold standard examples (or falls back to static ones),
    then runs the Pydantic AI classifier agent on the article.
    """
    if agent is None:
        model = get_ollama_model("32k-gemma-e4b", "OLLAMA_MODEL_RELEVANCE")
        agent = Agent(
            model,
            output_type=RelevanceClassification,
            instructions=RELEVANCE_AGENT_INSTRUCTIONS,
            defer_model_check=True
        )

    # Fetch examples from database
    try:
        from knowledge_map.adapters.sqlite_db import get_gold_standard_examples
        db_examples = get_gold_standard_examples(db_path)
    except Exception:
        db_examples = []

    positives = [e for e in db_examples if e.get("relevance_status") == "RELEVANT"]
    negatives = [e for e in db_examples if e.get("relevance_status") == "IRRELEVANT"]

    # Fallback to static examples if database examples are missing
    if not positives:
        positives = STATIC_POSITIVE_EXAMPLES
    if not negatives:
        negatives = STATIC_NEGATIVE_EXAMPLES

    prompt = get_relevance_agent_prompt(title, body, positives[:3], negatives[:3])
    result = await agent.run(prompt)
    return result.output
