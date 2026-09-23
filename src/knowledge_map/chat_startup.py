"""Assemble the local chat's fixed dependencies for one application lifetime."""

import hashlib
import json
import logging
import os
from collections.abc import AsyncIterator, Iterator
from contextlib import AsyncExitStack, asynccontextmanager, contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from importlib.resources import files
from pathlib import Path

import httpx
from dotenv import load_dotenv
from neo4j import READ_ACCESS, AsyncGraphDatabase
from pydantic import JsonValue
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel

from knowledge_map.adapters.audit import SQLiteAuditStore, audit_database_path
from knowledge_map.adapters.dense import Neo4jDenseRetriever
from knowledge_map.adapters.embedding import get_embedding_embedder
from knowledge_map.adapters.evidence import EvidenceStore
from knowledge_map.adapters.full_text import Neo4jFullTextRetriever
from knowledge_map.adapters.structural import (
    STRUCTURAL_INSTRUCTIONS,
    Neo4jStructuralRetriever,
    get_structural_agents,
)
from knowledge_map.core.audit import AuditWriter, code_revision
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
    audit: AuditWriter | None = None
    audit_settings: dict[str, JsonValue] | None = None


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
        audit=dependencies.audit,
        audit_settings=dependencies.audit_settings,
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
    *, coverage_path: Path | None = None
) -> AsyncIterator[ChatDependencies]:
    load_dotenv()
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
                coverage_observed_at = datetime.now(UTC)
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
        with _required("Query Rewriter deployment"):
            rewrite_deployment = query_rewriter_deployment_from_environment()
            rewriter = get_query_rewriter(rewrite_deployment, cache_model=False)
            assert isinstance(rewriter.model, OpenAIChatModel)
            resources.push_async_callback(rewriter.model.client.close)
        with _required("Chat Agent deployment"):
            chat_deployment = deployment_from_environment(
                os.environ.get("CHAT_DEPLOYMENT", "local"),
                default_local_model=DEFAULT_LOCAL_CHAT_MODEL,
                command_name="Chat Agent",
            )
            chat_agent = get_chat_agent(chat_deployment, cache_model=False)
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
        structural_agents = get_structural_agents(
            ontology_model=chat_agent.model,
            selection_model=chat_agent.model,
            wiring_model=chat_agent.model,
            binding_model=chat_agent.model,
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
            structural=Neo4jStructuralRetriever(
                driver, agents=structural_agents, database=database
            ),
            load_grounding=store.load_grounding,
            fusion_config=fusion,
            context_limits=context_limits,
        )
        audit = AuditWriter(SQLiteAuditStore(audit_database_path()))
        await audit.initialize()
        audit_settings: dict[str, JsonValue] | None = None
        try:
            deployments = {}
            for name, deployment, model in (
                ("query_rewriter", rewrite_deployment, rewriter.model),
                ("chat_agent", chat_deployment, chat_agent.model),
            ):
                resolved = deployment.model_dump(mode="json")
                if deployment.kind is DeploymentKind.LOCAL:
                    resolved["endpoint"] = str(model.client.base_url).rstrip("/")
                deployments[name] = resolved
            deployments.update(
                {name: deployments["chat_agent"] for name in STRUCTURAL_INSTRUCTIONS}
            )
            prompts = {
                "query_rewriter": QUERY_REWRITER_INSTRUCTIONS,
                "chat_agent": CHAT_INSTRUCTIONS,
                "question_policy": QUESTION_POLICY,
                **STRUCTURAL_INSTRUCTIONS,
            }
            audit_settings = {
                "code": code_revision(),
                "deployments": deployments,
                "prompt_revisions": {
                    name: "sha256:" + hashlib.sha256(text.encode()).hexdigest()
                    for name, text in prompts.items()
                },
                "fusion": fusion.model_dump(mode="json"),
                "context_limits": context_limits.model_dump(mode="json"),
                "coverage": coverage.model_dump(mode="json"),
                "coverage_observed_at": coverage_observed_at.isoformat(),
            }
        except Exception:
            logging.getLogger(__name__).exception("chat_audit_settings_failed")
        yield ChatDependencies(
            rewriter,
            chat_agent,
            retrieval,
            coverage,
            rewrite_deployment,
            chat_deployment,
            audit,
            audit_settings,
        )
