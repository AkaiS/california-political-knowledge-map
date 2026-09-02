"""The Policy Area adapter: classification today, assignment in issue 04.

A Source Article's Policy Areas are decided once, for the article, over the
coreference-resolved text and before it is cut into chunks.  Both halves of the
article-level topic judgement sit behind this one adapter, so the Story
Pipeline gains one collaborator rather than two.

The stage owns the vocabulary.  The agent's output type admits the canonical
names the News Ontology declares and nothing else, so a model cannot answer
with an id where the write path keys on a name.
"""

import logging

from pydantic import ValidationError
from pydantic_ai import Agent
from pydantic_ai.exceptions import UnexpectedModelBehavior

from knowledge_map.adapters.coreference import get_agent_metadata
from knowledge_map.ontology import news
from knowledge_map.schemas import ModelDeployment, PolicyAreaClassification
from knowledge_map.utils.agents import create_agent
from knowledge_map.utils.models import DEFAULT_LOCAL_CHAT_MODEL, get_chat_model

logger = logging.getLogger(__name__)

#: Caught by the adapter and reported as a classification failure.  Transport
#: failures are deliberately not among them: the pipeline classifies those by
#: the same connectivity and rate-limit handling every other stage call uses.
MODEL_OUTPUT_FAILURES: tuple[type[Exception], ...] = (
    ValidationError,
    UnexpectedModelBehavior,
)


def render_policy_area_vocabulary() -> str:
    """The closed vocabulary as one line per area, named the way it is keyed."""

    return "\n".join(f"- {area.name}" for area in news.POLICY_AREAS)


CLASSIFICATION_INSTRUCTIONS = f"""\
You are classifying one California politics news article by the policy areas it
discusses.

Choose from this closed vocabulary, copying a name exactly as written:

{render_policy_area_vocabulary()}

Return every area the article discusses and no others.  An area belongs in the
answer when the article's discussion is about it, not when a word from its name
merely appears.  There is no minimum and no maximum: an article the vocabulary
does not cover returns an empty list.
"""


def get_classification_agent(
    deployment: ModelDeployment | None = None,
    *,
    defer_check: bool = True,
    retries: int = 3,
) -> Agent:
    """Build the Policy Area Classification agent from one explicit deployment.

    Callers without a deployment use the configured local chat deployment.
    """

    model = (
        get_chat_model(deployment)
        if deployment is not None
        else get_chat_model(DEFAULT_LOCAL_CHAT_MODEL)
    )

    return create_agent(
        model,
        name="policy_area_classifier",
        output_type=PolicyAreaClassification,
        instructions=CLASSIFICATION_INSTRUCTIONS,
        defer_model_check=defer_check,
        retries=retries,
    )


class PolicyAreaClassificationError(Exception):
    """One Source Article's classification could not be used.

    Carries what the Dead Letter Queue records, as the coreference and
    extraction failures beside it do.
    """

    def __init__(
        self,
        original_text: str,
        validation_issues: list[str] | None = None,
        failure_type: str = "policy_area_classification_failure",
        retry_count: int = 0,
        metadata: dict | None = None,
    ) -> None:
        self.original_text = original_text
        self.validation_issues = validation_issues or []
        self.failure_type = failure_type
        self.retry_count = retry_count
        self.metadata = metadata or {}
        super().__init__(f"Policy Area classification failed: {failure_type}")


def _validation_issues_from_error(error: Exception) -> list[str]:
    """Describe an unusable answer for the Dead Letter Queue record."""

    if isinstance(error, ValidationError):
        return [
            f"{' -> '.join(str(part) for part in issue.get('loc', ()))}: "
            f"{issue.get('msg', 'Validation error')}"
            for issue in error.errors()
        ]
    return [str(error) or "Classification output could not be parsed"]


class PydanticAIPolicyAreaAdapter:
    """Concrete Policy Area adapter conforming to the PolicyAreaAdapter Protocol."""

    def __init__(
        self,
        agent: Agent | None = None,
        *,
        deployment: ModelDeployment | None = None,
    ) -> None:
        self.deployment = deployment
        self.agent = agent or get_classification_agent(deployment)

    def classify(self, resolved_text: str) -> list[str]:
        """The Policy Areas the article discusses, by canonical name."""

        try:
            result = self.agent.run_sync(resolved_text)
        except MODEL_OUTPUT_FAILURES as error:
            raise PolicyAreaClassificationError(
                original_text=resolved_text,
                validation_issues=_validation_issues_from_error(error),
                retry_count=getattr(self.agent, "retries", 0),
                metadata=get_agent_metadata(self.agent, CLASSIFICATION_INSTRUCTIONS),
            ) from error

        areas = list(result.output.policy_areas)
        logger.info("Classified article into %d Policy Area(s)", len(areas))
        return areas

    def health_check(self) -> bool:
        """Report whether the classifier can complete a trivial run.

        Any completed run is healthy, whatever it returned.
        """

        try:
            result = self.agent.run_sync(
                "health_check", model_settings={"max_tokens": 1}
            )
            return result is not None
        except Exception:
            return False
