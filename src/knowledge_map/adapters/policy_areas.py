"""The Policy Area adapter: classification before chunking, assignment after.

A Source Article's Policy Areas are decided once, for the article, over the
coreference-resolved text and before it is cut into chunks.  Which of those
areas each measure is about is decided once too, after extraction has
discovered the measures.  Both halves of the article-level topic judgement sit
behind this one adapter.

The stage owns the vocabulary.  The agent is asked for the canonical names the
News Ontology declares, and its output type keeps only those, so a model cannot
answer with an id where the write path keys on a name.
"""

import logging

from pydantic import ValidationError
from pydantic_ai import Agent
from pydantic_ai.exceptions import UnexpectedModelBehavior

from knowledge_map.adapters.coreference import get_agent_metadata
from knowledge_map.ontology import news
from knowledge_map.prompts import load_prompt
from knowledge_map.schemas import (
    ModelDeployment,
    Node,
    PolicyAreaClassification,
    SourceArticle,
    TopicAssignment,
    TopicAssignments,
)
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


CLASSIFICATION_INSTRUCTIONS = load_prompt(
    "policy-areas/classification-instructions", version=1
).format(vocabulary=render_policy_area_vocabulary())


def _get_stage_agent(
    deployment: ModelDeployment | None,
    *,
    name: str,
    output_type: type,
    instructions: str,
    defer_check: bool,
    retries: int,
) -> Agent:
    """Build one of the two stages' agents from one explicit deployment.

    The stages differ only in name, output type and instructions; they are
    built alike so a change to how either reaches its model reaches both.
    Callers without a deployment use the configured local chat deployment.
    """

    model = get_chat_model(
        deployment if deployment is not None else DEFAULT_LOCAL_CHAT_MODEL
    )

    return create_agent(
        model,
        name=name,
        output_type=output_type,
        instructions=instructions,
        defer_model_check=defer_check,
        retries=retries,
    )


def get_classification_agent(
    deployment: ModelDeployment | None = None,
    *,
    defer_check: bool = True,
    retries: int = 3,
) -> Agent:
    """Build the Policy Area Classification agent from one explicit deployment."""

    return _get_stage_agent(
        deployment,
        name="policy_area_classifier",
        output_type=PolicyAreaClassification,
        instructions=CLASSIFICATION_INSTRUCTIONS,
        defer_check=defer_check,
        retries=retries,
    )


ASSIGNMENT_INSTRUCTIONS = load_prompt("policy-areas/assignment-instructions", version=1)


def render_assignment_request(
    article: SourceArticle,
    policy_areas: list[str],
    measures: list[Node],
) -> str:
    """The article, its areas, and its measures, as one prompt.

    Measures are named by the surface strings extraction produced, which is
    what keeps an assignment from inventing a Bill the article never mentioned.
    """

    rendered_areas = "\n".join(f"- {area}" for area in policy_areas)
    rendered_measures = "\n".join(
        f"- {measure.name} ({measure.label})" for measure in measures
    )
    return load_prompt("policy-areas/assignment-request", version=1).format(
        title=article.title or "",
        content=article.content,
        rendered_areas=rendered_areas,
        rendered_measures=rendered_measures,
    )


def get_assignment_agent(
    deployment: ModelDeployment | None = None,
    *,
    defer_check: bool = True,
    retries: int = 3,
) -> Agent:
    """Build the Topic Assignment agent from one explicit deployment."""

    return _get_stage_agent(
        deployment,
        name="topic_assigner",
        output_type=TopicAssignments,
        instructions=ASSIGNMENT_INSTRUCTIONS,
        defer_check=defer_check,
        retries=retries,
    )


class ArticleStageError(Exception):
    """One article-level stage's answer could not be used.

    Carries what the Dead Letter Queue records, as the coreference and
    extraction failures beside it do.  The two stages behind this adapter run
    at different points in the pipeline, so each raises its own subclass: a
    Dead Letter Queue record has to say which stage the article did not
    survive.
    """

    #: Names the stage in the record and in the raised message.
    stage: str = "article stage"
    default_failure_type: str = "article_stage_failure"

    def __init__(
        self,
        original_text: str,
        validation_issues: list[str] | None = None,
        failure_type: str | None = None,
        retry_count: int = 0,
        metadata: dict | None = None,
    ) -> None:
        self.original_text = original_text
        self.validation_issues = validation_issues or []
        self.failure_type = failure_type or self.default_failure_type
        self.retry_count = retry_count
        self.metadata = metadata or {}
        super().__init__(f"{self.stage} failed: {self.failure_type}")


class PolicyAreaClassificationError(ArticleStageError):
    """One Source Article's classification could not be used."""

    stage = "Policy Area classification"
    default_failure_type = "policy_area_classification_failure"


class TopicAssignmentError(ArticleStageError):
    """One Source Article's Topic Assignment could not be used."""

    stage = "Topic Assignment"
    default_failure_type = "topic_assignment_failure"


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
        assignment_agent: Agent | None = None,
        deployment: ModelDeployment | None = None,
    ) -> None:
        self.deployment = deployment
        self.agent = agent or get_classification_agent(deployment)
        self.assignment_agent = assignment_agent or get_assignment_agent(deployment)

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

    def assign(
        self,
        article: SourceArticle,
        policy_areas: list[str],
        measures: list[Node],
    ) -> list[TopicAssignment]:
        """Which of the article's Policy Areas each of its measures is about."""

        request = render_assignment_request(article, policy_areas, measures)
        try:
            result = self.assignment_agent.run_sync(request)
        except MODEL_OUTPUT_FAILURES as error:
            raise TopicAssignmentError(
                original_text=article.content,
                validation_issues=_validation_issues_from_error(error),
                retry_count=getattr(self.assignment_agent, "retries", 0),
                metadata=get_agent_metadata(
                    self.assignment_agent, ASSIGNMENT_INSTRUCTIONS
                ),
            ) from error

        assignments = list(result.output.assignments)
        logger.info("Assigned %d measure-to-area topic edge(s)", len(assignments))
        return assignments

    def health_check(self) -> bool:
        """Report whether both stages behind this adapter can complete a run.

        Any completed run is healthy, whatever it returned.  Both agents are
        probed because either stage's component name clears a lock through this
        one check, and the two can be built from different Model Deployments —
        probing only the classifier would clear an assignment lock on the
        strength of a model assignment never runs on.
        """

        for agent in (self.agent, self.assignment_agent):
            try:
                result = agent.run_sync(
                    load_prompt("shared/health-check", version=1), model_settings={"max_tokens": 1}
                )
            except Exception:
                return False
            if result is None:
                return False
        return True
