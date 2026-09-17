"""Typed semantic construction followed by read-only Neo4j retrieval."""

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Literal, LiteralString, cast

import httpx
from neo4j import READ_ACCESS, AsyncDriver, Query
from neo4j.exceptions import DriverError, Neo4jError
from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelAPIError, UnexpectedModelBehavior
from pydantic_ai.models import Model
from pydantic_ai.usage import RunUsage

from knowledge_map.core.structural import (
    CATALOG,
    compile_query,
    filtered_catalog,
    public_pieces,
    selected_pieces,
    validate_wiring,
)
from knowledge_map.ontology import news
from knowledge_map.schemas.retrieval import (
    BranchCandidate,
    BranchRanking,
    FailedBranch,
    GraphClaim,
    GraphNodeReference,
    GroundingEvidence,
    RetrievalBranch,
    RetrievalFailureLog,
    RetrievalRequest,
    RetrievalRoute,
    SourceArticleCitation,
    SuccessfulBranch,
)
from knowledge_map.schemas.structural import (
    OntologySelection,
    PieceSelection,
    PositionalBindings,
    SemanticWiring,
)
from knowledge_map.utils.agents import create_agent

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StructuralAgents:
    ontology_filter: Agent[None, OntologySelection]
    selector: Agent[None, PieceSelection]
    wiring: Agent[None, SemanticWiring]
    binder: Agent[None, PositionalBindings]


def get_structural_agents(
    *,
    ontology_model: Model,
    selection_model: Model,
    wiring_model: Model,
    binding_model: Model,
) -> StructuralAgents:
    common = (
        "Use only the approved question and supplied semantic choices. "
        "Never emit Cypher, graph identifiers, variables, parameters, projections, or provenance paths. "
    )
    return StructuralAgents(
        ontology_filter=cast(
            Agent[None, OntologySelection],
            create_agent(
                ontology_model,
                name="structural_ontology_filter",
                retries=0,
                output_type=OntologySelection,
                instructions=common
                + "Select relevant labels, relationships, and filter properties.",
            ),
        ),
        selector=cast(
            Agent[None, PieceSelection],
            create_agent(
                selection_model,
                name="structural_selector",
                retries=0,
                output_type=PieceSelection,
                instructions=common
                + "Select only supplied piece IDs, keeping separate occurrences for each role.",
            ),
        ),
        wiring=cast(
            Agent[None, SemanticWiring],
            create_agent(
                wiring_model,
                name="structural_wiring",
                retries=0,
                output_type=SemanticWiring,
                instructions=common
                + "Wire selected occurrences by zero-based numeric index. Use each filter and relationship once.",
            ),
        ),
        binder=cast(
            Agent[None, PositionalBindings],
            create_agent(
                binding_model,
                name="structural_binder",
                retries=0,
                output_type=PositionalBindings,
                instructions=common
                + "Return question values in supplied filter order. Preserve Bill names for deterministic parsing.",
            ),
        ),
    )


class Neo4jStructuralRetriever:
    def __init__(
        self, driver: AsyncDriver, *, agents: StructuralAgents, database: str = "neo4j"
    ) -> None:
        self.driver = driver
        self.agents = agents
        self.database = database

    async def retrieve(
        self, request: RetrievalRequest, *, deadline: float
    ) -> SuccessfulBranch | FailedBranch:
        stage: Literal[
            "schema_filtering",
            "typed_selection",
            "wiring",
            "binding",
            "validation",
            "cypher_execution",
            "hydration",
            "deadline",
        ] = "schema_filtering"
        attempts = 0
        usage = RunUsage()
        try:
            _remaining(deadline)
            async with asyncio.timeout_at(deadline):
                attempts = 1
                question = request.rewrite.question
                ontology = (
                    await self.agents.ontology_filter.run(
                        json.dumps(
                            {
                                "question": question,
                                "catalog": public_pieces(CATALOG),
                            }
                        ),
                        usage=usage,
                    )
                ).output
                catalog = filtered_catalog(ontology)
                stage = "typed_selection"
                selection = (
                    await self.agents.selector.run(
                        json.dumps(
                            {
                                "question": question,
                                "catalog": public_pieces(catalog),
                            }
                        ),
                        usage=usage,
                    )
                ).output
                pieces = selected_pieces(selection, catalog)
                chosen = {kind: public_pieces(items) for kind, items in pieces.items()}
                stage = "wiring"
                wiring = (
                    await self.agents.wiring.run(
                        json.dumps({"question": question, "pieces": chosen}),
                        usage=usage,
                    )
                ).output
                validate_wiring(wiring, pieces)
                stage = "binding"
                bindings = (
                    await self.agents.binder.run(
                        json.dumps(
                            {
                                "question": question,
                                "filters": [
                                    public_pieces(
                                        (pieces["filter"][item.filter_index],)
                                    )[0]
                                    for item in wiring.filters
                                ],
                            }
                        ),
                        usage=usage,
                    )
                ).output
                stage = "validation"
                cypher, parameters = compile_query(pieces, wiring, bindings)
                stage = "cypher_execution"
                async with self.driver.session(
                    database=self.database, default_access_mode=READ_ACCESS
                ) as session:
                    result = await session.run(
                        Query(
                            cast(LiteralString, cypher), timeout=_remaining(deadline)
                        ),
                        parameters=parameters,
                    )
                    rows = await result.data()
                stage = "hydration"
                outcome = SuccessfulBranch(
                    branch=RetrievalBranch.STRUCTURAL,
                    candidates=tuple(
                        BranchCandidate(
                            chunk_id=row["chunk_id"],
                            source_article_id=row["source_article_id"],
                            ranking=BranchRanking(
                                branch=RetrievalBranch.STRUCTURAL, rank=rank, score=None
                            ),
                            routes=(
                                RetrievalRoute(
                                    kind="typed_traversal",
                                    matched_field=None,
                                    entry_node=GraphNodeReference(
                                        id=row["entry_id"],
                                        label=pieces["role"][0].label,
                                        element_id=row["element_id"],
                                    ),
                                    graph_claims=_claims(row, pieces),
                                ),
                            ),
                            grounding=GroundingEvidence(
                                chunk_id=row["chunk_id"],
                                text=row["text"],
                                citation=SourceArticleCitation(
                                    source_article_id=row["source_article_id"],
                                    title=row["title"],
                                    url=row["url"],
                                    published_date=row["published_date"],
                                ),
                            ),
                        )
                        for rank, row in enumerate(rows, 1)
                    ),
                )
                _remaining(deadline)
                return outcome
        except TimeoutError:
            stage, kind = "deadline", "deadline_exhausted"
        except (ModelAPIError, httpx.TransportError):
            kind = "transport"
        except UnexpectedModelBehavior:
            kind = "model_output"
        except (DriverError, Neo4jError) as error:
            if (
                isinstance(error, Neo4jError)
                and ".Transaction.TransactionTimedOut" in error.code
            ):
                stage, kind = "deadline", "deadline_exhausted"
            else:
                kind = "database"
        except (KeyError, TypeError, ValueError):
            kind = "hydration" if stage == "hydration" else "validation"
        finally:
            logger.info(
                "retrieval_model_usage",
                extra={
                    "event": "retrieval_model_usage",
                    "branch": "structural",
                    "requests": usage.requests,
                    "input_tokens": usage.input_tokens,
                    "output_tokens": usage.output_tokens,
                },
            )
        return _failed(
            RetrievalFailureLog.model_validate(
                {
                    "branch": "structural",
                    "stage": stage,
                    "failure_kind": kind,
                    "attempts_consumed": attempts,
                    "safe_diagnostic": "Structural retrieval could not complete this stage.",
                }
            )
        )


def _remaining(deadline: float) -> float:
    remaining = deadline - asyncio.get_running_loop().time()
    if remaining <= 0:
        raise TimeoutError
    return remaining


def _failed(diagnostic: RetrievalFailureLog) -> FailedBranch:
    logger.warning(
        "retrieval_branch_failed",
        extra={
            "event": "retrieval_branch_failed",
            **diagnostic.model_dump(),
            "deadline_exhausted": diagnostic.deadline_exhausted,
        },
    )
    return FailedBranch(branch=RetrievalBranch.STRUCTURAL)


def _claims(row, pieces) -> tuple[GraphClaim, ...]:
    if not pieces["relationship"]:
        return ()
    piece = pieces["relationship"][0]
    props = row["claim_properties"]
    article_level = piece.predicate in {"ABOUT_TOPIC", "DISCUSSES_TOPIC"}
    return (
        GraphClaim(
            source=GraphNodeReference(
                id=row["source_id"],
                label=piece.label,
                element_id=row["source_element_id"],
            ),
            target=GraphNodeReference(
                id=row["target_id"],
                label=piece.target,
                element_id=row["target_element_id"],
            ),
            relationship_type=row["relationship_type"],
            claim_key={
                key: props[key]
                for key in sorted(news.claim_key_properties(row["relationship_type"]))
                if key in props
            },
            chunk_ids=() if article_level else tuple(props.get("chunks", ())),
            source_article_ids=tuple(props.get("articles", ()))
            if article_level
            else (),
            needs_review=props.get("needs_review", False),
        ),
    )
