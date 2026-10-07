"""Assemble the local chat's fixed dependencies for one application lifetime."""

import hashlib
import json
import os
from collections.abc import AsyncIterator, Iterator, Sequence
from contextlib import AsyncExitStack, asynccontextmanager, contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from importlib.resources import files
from pathlib import Path

import httpx
from dotenv import load_dotenv
from neo4j import READ_ACCESS, AsyncGraphDatabase, GraphDatabase
from pydantic_ai import Agent
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.embeddings.openai import OpenAIEmbeddingModel
from pydantic_ai.models.openai import OpenAIChatModel

from knowledge_map.adapters.dense import Neo4jDenseRetriever
from knowledge_map.adapters.embedding import get_embedding_embedder
from knowledge_map.adapters.evidence import EvidenceStore
from knowledge_map.adapters.full_text import Neo4jFullTextRetriever
from knowledge_map.adapters.jev import (
    JevStructuralRetriever,
    get_jev_agents,
    jev_client,
)
from knowledge_map.chat_telemetry import ChatSessionSettings, code_state
from knowledge_map.core.chat import (
    CHAT_INSTRUCTIONS,
    QUESTION_POLICY,
    ChatSession,
    get_chat_agent,
)
from knowledge_map.core.question_preparation import (
    QUERY_REWRITER_INSTRUCTIONS,
    get_query_rewriter,
)
from knowledge_map.core.retrieval import RetrievalCoordinator
from knowledge_map.jev.prompts import JEV_PROMPTS
from knowledge_map.schemas import DeploymentKind, ModelDeployment
from knowledge_map.schemas.evidence import EvidenceContextLimits
from knowledge_map.schemas.fusion import FusionConfig
from knowledge_map.schemas.query_preparation import (
    QueryRewriteProposal,
    QuestionAssessment,
)
from knowledge_map.schemas.retrieval import CoverageDescription, CoverageEntry
from knowledge_map.utils.deployments import (
    deployment_from_environment,
    query_rewriter_deployment_from_environment,
)
from knowledge_map.utils.models import DEFAULT_LOCAL_CHAT_MODEL, build_retrying_client
from knowledge_map.utils.reachability import (
    model_reachability_check_skipped,
    request_model_listing,
)


@dataclass(frozen=True)
class ChatDependencies:
    rewriter: Agent[None, QueryRewriteProposal]
    chat_agent: Agent[None, QuestionAssessment]
    retrieval: RetrievalCoordinator
    coverage: CoverageDescription
    rewriter_deployment: ModelDeployment
    chat_deployment: ModelDeployment
    start_settings: ChatSessionSettings


def new_chat_session(
    question: str, dependencies: ChatDependencies | None
) -> ChatSession:
    assert dependencies is not None
    return ChatSession(
        question,
        rewriter=dependencies.rewriter,
        chat_agent=dependencies.chat_agent,
        retrieval=dependencies.retrieval,
        coverage=dependencies.coverage,
        relevant_collection_ids=("calmatters",),
        monthly_coverage=(),
        start_settings=dependencies.start_settings,
    )


def _publication_date_range(
    stored_values: list[object],
) -> tuple[date | None, date | None]:
    parsed: list[date] = []
    for value in stored_values:
        if not isinstance(value, str):
            continue
        try:
            parsed.append(date.fromisoformat(value[:10]))
        except ValueError:
            continue
    if not parsed:
        return None, None
    return min(parsed), max(parsed)


@contextmanager
def _required(dependency: str) -> Iterator[None]:
    try:
        yield
    except Exception as error:
        raise RuntimeError(
            f"{dependency} is unavailable; chat startup cannot continue."
        ) from error


@asynccontextmanager
async def chat_dependencies(
    *,
    coverage_path: Path | None = None,
    chat_deployment: ModelDeployment | None = None,
    capabilities: Sequence[AbstractCapability] = (),
) -> AsyncIterator[ChatDependencies]:
    load_dotenv()
    code_revision, worktree_dirty = code_state()
    async with AsyncExitStack() as resources:
        with _required("Neo4j"):
            driver = AsyncGraphDatabase.driver(
                os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
                auth=(
                    os.environ.get("NEO4J_USERNAME", "neo4j"),
                    os.environ.get("NEO4J_PASSWORD", ""),
                ),
                connection_timeout=5,
            )
            resources.push_async_callback(driver.close)
            await driver.verify_connectivity()
        database = os.environ.get("NEO4J_DATABASE", "neo4j")
        with _required("CalMatters coverage"):
            authored = json.loads(
                coverage_path.read_text()
                if coverage_path
                else files("knowledge_map")
                .joinpath("resources/calmatters-coverage.json")
                .read_text()
            )
            async with driver.session(
                database=database, default_access_mode=READ_ACCESS
            ) as session:
                result = await session.run(
                    "MATCH (article:NewsArticle)-[:HAS_CHUNK]->(:Chunk) "
                    "WHERE any(prefix IN $prefixes WHERE article.id STARTS WITH prefix) "
                    "WITH DISTINCT article RETURN count(article) AS available_count, "
                    "collect(DISTINCT article.published_date) AS publication_dates",
                    parameters={
                        "prefixes": [
                            "https://calmatters.org/",
                            "https://www.calmatters.org/",
                            "http://calmatters.org/",
                            "http://www.calmatters.org/",
                        ]
                    },
                )
                inventory = (await result.data())[0]
            if inventory["available_count"] == 0:
                raise ValueError(
                    "No CalMatters Source Articles with Article Chunks are available"
                )
            earliest_date, latest_date = _publication_date_range(
                inventory["publication_dates"]
            )
            coverage = CoverageDescription(
                entries=(
                    CoverageEntry.model_validate(
                        {
                            **authored,
                            "availability": {
                                "available_count": inventory["available_count"]
                            },
                            "earliest_date": earliest_date,
                            "latest_date": latest_date,
                        }
                    ),
                )
            )
            coverage_observed_at = datetime.now(UTC)
        with _required("Query Rewriter deployment"):
            rewrite_deployment = query_rewriter_deployment_from_environment()
            rewriter = get_query_rewriter(
                rewrite_deployment, cache_model=False, capabilities=capabilities
            )
            assert isinstance(rewriter.model, OpenAIChatModel)
            resources.push_async_callback(rewriter.model.client.close)
        with _required("Chat Agent deployment"):
            chat_deployment = chat_deployment or deployment_from_environment(
                os.environ.get("CHAT_DEPLOYMENT", "local"),
                default_local_model=DEFAULT_LOCAL_CHAT_MODEL,
                command_name="Chat Agent",
            )
            chat_agent = get_chat_agent(
                chat_deployment, cache_model=False, capabilities=capabilities
            )
            assert isinstance(chat_agent.model, OpenAIChatModel)
            resources.push_async_callback(chat_agent.model.client.close)
        if not model_reachability_check_skipped():
            async with httpx.AsyncClient(timeout=5) as probe:
                for name, deployment, model in (
                    ("Query Rewriter", rewrite_deployment, rewriter.model),
                    ("Chat Agent", chat_deployment, chat_agent.model),
                ):
                    if deployment.kind is DeploymentKind.OPENROUTER:
                        continue
                    with _required(f"{name} deployment"):
                        await request_model_listing(
                            str(model.client.base_url), client=probe
                        )
        embedding_client = await resources.enter_async_context(build_retrying_client())
        embedder = get_embedding_embedder(http_client=embedding_client)
        with _required("Jev"):
            client = jev_client()
            resources.callback(client.close)
            sync_driver = GraphDatabase.driver(
                os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
                auth=(
                    os.environ.get("NEO4J_USERNAME", "neo4j"),
                    os.environ.get("NEO4J_PASSWORD", ""),
                ),
                connection_timeout=5,
            )
            resources.callback(sync_driver.close)
            structural_agents = get_jev_agents(
                chat_agent.model, capabilities=capabilities
            )
        store = EvidenceStore(driver, database=database)
        fusion = FusionConfig()
        context_limits = EvidenceContextLimits()
        retrieval = RetrievalCoordinator(
            full_text=Neo4jFullTextRetriever(driver, database=database),
            dense=Neo4jDenseRetriever(
                driver,
                embedder,
                candidate_limit=fusion.dense_candidate_limit,
                database=database,
            ),
            structural=JevStructuralRetriever(
                driver,
                sync_driver=sync_driver,
                client=client,
                agents=structural_agents,
                database=database,
            ),
            load_grounding=store.load_grounding,
            fusion_config=fusion,
            context_limits=context_limits,
            structural_reporting=True,
            deadline_seconds=180,
        )
        chat_snapshot = {
            **chat_deployment.model_dump(mode="json"),
            "endpoint": str(chat_agent.model.client.base_url),
        }
        assert isinstance(embedder.model, OpenAIEmbeddingModel)
        embedding_url = httpx.URL(embedder.model.base_url).copy_with(
            username=None, password=None, query=None, fragment=None
        )
        start_settings = ChatSessionSettings(
            code_revision=code_revision,
            worktree_dirty=worktree_dirty,
            model_deployments={
                "query_rewriter": {
                    **rewrite_deployment.model_dump(mode="json"),
                    "endpoint": str(rewriter.model.client.base_url),
                },
                "chat_agent": chat_snapshot,
                **{role: chat_snapshot for role in ("jev_composer", "jev_binder")},
            },
            embedding_settings={
                "model": embedder.model.model_name,
                "endpoint": str(embedding_url),
            },
            prompt_hashes={
                role: "sha256:"
                + hashlib.sha256(prompt.strip().encode("utf-8")).hexdigest()
                for role, prompt in {
                    "query_rewriter": QUERY_REWRITER_INSTRUCTIONS,
                    "chat_agent": CHAT_INSTRUCTIONS,
                    "question_policy": QUESTION_POLICY,
                    **JEV_PROMPTS,
                }.items()
            },
            fusion_settings=fusion,
            evidence_limits=context_limits,
            coverage_observed_at=coverage_observed_at.isoformat(),
            retrieval_settings={
                "cypher_backend": "jev-staged",
                "schema_threshold": 0.8,
                "structure_threshold": 0.52,
                "subtype_threshold": 0.8,
                "property_threshold": 0.52,
                "reporting_threshold": 0.52,
                "deadline_seconds": 180,
                "structural_reporting": True,
            },
        )
        yield ChatDependencies(
            rewriter,
            chat_agent,
            retrieval,
            coverage,
            rewrite_deployment,
            chat_deployment,
            start_settings,
        )
