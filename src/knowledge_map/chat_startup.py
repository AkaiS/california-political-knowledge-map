"""Assemble the local chat's fixed dependencies for one application lifetime."""

import asyncio
import json
import os
import sqlite3
from collections.abc import AsyncIterator, Iterator
from contextlib import AsyncExitStack, asynccontextmanager, closing, contextmanager
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

import httpx
from dotenv import load_dotenv
from neo4j import READ_ACCESS, AsyncGraphDatabase
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel

from knowledge_map.adapters.dense import Neo4jDenseRetriever
from knowledge_map.adapters.embedding import get_embedding_embedder
from knowledge_map.adapters.evidence import EvidenceStore
from knowledge_map.adapters.full_text import Neo4jFullTextRetriever
from knowledge_map.adapters.structural import (
    Neo4jStructuralRetriever,
    get_structural_agents,
)
from knowledge_map.core.chat import ChatSession, get_chat_agent
from knowledge_map.core.question_preparation import get_query_rewriter
from knowledge_map.core.retrieval import RetrievalCoordinator
from knowledge_map.schemas import ModelDeployment
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


@dataclass(frozen=True)
class ChatDependencies:
    rewriter: Agent[None, QueryRewriteProposal]
    chat_agent: Agent[None, QuestionAssessment]
    retrieval: RetrievalCoordinator
    coverage: CoverageDescription
    rewriter_deployment: ModelDeployment
    chat_deployment: ModelDeployment


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
    )


def _check_document_store(path: Path) -> None:
    with closing(
        sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=0)
    ) as connection:
        connection.execute(
            "SELECT id, title, url, category, author, published_date, summary, content, status FROM stories LIMIT 0"
        )
        connection.execute("SELECT id, story_id, text, url FROM story_links LIMIT 0")


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
    story_path = Path(os.environ.get("SQLITE_DB_PATH", "document_store.db"))
    with _required("SQLite document store"):
        await asyncio.to_thread(_check_document_store, story_path)
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
                    "min(substring(article.published_date, 0, 10)) AS earliest_date, "
                    "max(substring(article.published_date, 0, 10)) AS latest_date",
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
            coverage = CoverageDescription(
                entries=(
                    CoverageEntry.model_validate(
                        {
                            **authored,
                            "availability": {
                                "available_count": inventory["available_count"]
                            },
                            "earliest_date": inventory["earliest_date"],
                            "latest_date": inventory["latest_date"],
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
        async with httpx.AsyncClient(timeout=5) as probe:
            for name, model in (
                ("Query Rewriter", rewriter.model),
                ("Chat Agent", chat_agent.model),
            ):
                with _required(f"{name} deployment"):
                    response = await probe.get(
                        str(model.client.base_url.join("models")),
                        headers={"Authorization": f"Bearer {model.client.api_key}"},
                    )
                    response.raise_for_status()
        embedding_client = await resources.enter_async_context(build_retrying_client())
        embedder = get_embedding_embedder(http_client=embedding_client)
        structural_agents = get_structural_agents(
            ontology_model=chat_agent.model,
            selection_model=chat_agent.model,
            wiring_model=chat_agent.model,
            binding_model=chat_agent.model,
        )
        store = EvidenceStore(driver, story_db_path=str(story_path), database=database)
        fusion = FusionConfig()
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
            load_story=store.load_story,
            fusion_config=fusion,
        )
        yield ChatDependencies(
            rewriter,
            chat_agent,
            retrieval,
            coverage,
            rewrite_deployment,
            chat_deployment,
        )
