"""Typed semantic construction followed by read-only Neo4j retrieval."""

import asyncio
import json
import logging
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from typing import Any, Literal, LiteralString, cast

import httpx
import logfire
from neo4j import READ_ACCESS, AsyncDriver, Query
from neo4j.exceptions import DriverError, Neo4jError
from pydantic_ai import Agent, ModelRetry, RunContext
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.exceptions import ModelAPIError, UnexpectedModelBehavior
from pydantic_ai.models import Model
from pydantic_ai.usage import RunUsage

from knowledge_map.core.structural import (
    CATALOG,
    HopBoundError,
    Piece,
    compile_query,
    filtered_catalog,
    public_pieces,
    selected_pieces,
    validate_wiring,
)
from knowledge_map.ontology import news
from knowledge_map.prompts import load_prompt
from knowledge_map.retrieval_telemetry import record_branch_failure, structural_stage
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


@dataclass
class ConstructionValidation:
    check: Callable[[Any], object]
    stage: Literal["schema_filtering", "typed_selection", "wiring", "validation"]
    rejected_request: int = -1
    hop_bound: bool = False
    result: object | None = None


@contextmanager
def _stage(
    stage: str,
    *,
    validation: ConstructionValidation | None = None,
    usage: RunUsage | None = None,
    deadline: float | None = None,
) -> Iterator[logfire.LogfireSpan | None]:
    with structural_stage(stage) as span:
        try:
            yield span
        except (Exception, asyncio.CancelledError) as error:
            failure_stage = stage
            if isinstance(error, TimeoutError) or (
                isinstance(error, asyncio.CancelledError)
                and deadline is not None
                and asyncio.get_running_loop().time() >= deadline
            ):
                kind = "deadline_exhausted"
            elif isinstance(error, asyncio.CancelledError):
                kind = "cancelled"
            elif isinstance(error, (ModelAPIError, httpx.TransportError)):
                kind = "transport"
            elif isinstance(error, UnexpectedModelBehavior):
                kind = "model_output"
                if (
                    validation is not None
                    and usage is not None
                    and (validation.rejected_request == usage.requests)
                ):
                    failure_stage = validation.stage
                    kind = (
                        "hop_bound_exhausted" if validation.hop_bound else "validation"
                    )
            elif isinstance(error, (DriverError, Neo4jError)):
                kind = (
                    "deadline_exhausted"
                    if isinstance(error, Neo4jError)
                    and ".Transaction.TransactionTimedOut" in error.code
                    else "database"
                )
            elif isinstance(error, HopBoundError):
                kind = "hop_bound_exhausted"
            elif isinstance(error, (KeyError, TypeError, ValueError)):
                kind = "hydration" if stage == "hydration" else "validation"
            else:
                kind = "unexpected"
            if span is not None:
                span.set_attributes(
                    {
                        "status": "failed",
                        "failure_stage": failure_stage,
                        "failure_kind": kind,
                        "diagnostic": "Structural retrieval could not complete this stage.",
                    }
                )
            raise


def _validated_output(ctx: RunContext[ConstructionValidation], output: Any) -> Any:
    try:
        with (
            _stage("validation") if ctx.deps.stage == "validation" else nullcontext()
        ) as span:
            ctx.deps.result = ctx.deps.check(output)
            if span is not None:
                cypher, parameters = cast(tuple[str, dict[str, str]], ctx.deps.result)
                span.set_attributes(
                    {"validated_query": cypher, "bound_values": parameters}
                )
    except ValueError as error:
        ctx.deps.rejected_request = ctx.usage.requests
        ctx.deps.hop_bound = isinstance(error, HopBoundError)
        raise ModelRetry(str(error)) from error
    return output


@dataclass(frozen=True)
class StructuralAgents:
    ontology_filter: Agent[ConstructionValidation, OntologySelection]
    selector: Agent[ConstructionValidation, PieceSelection]
    wiring: Agent[ConstructionValidation, SemanticWiring]
    binder: Agent[ConstructionValidation, PositionalBindings]




STRUCTURAL_INSTRUCTIONS = {
    "structural_ontology_filter": load_prompt(
        "structural/ontology-filter-instructions", version=1
    ),
    "structural_selector": (load_prompt("structural/selector-instructions", version=1)),
    "structural_wiring": (load_prompt("structural/wiring-instructions", version=1)),
    "structural_binder": (load_prompt("structural/binder-instructions", version=1)),
}


def get_structural_agents(
    *,
    ontology_model: Model,
    selection_model: Model,
    wiring_model: Model,
    binding_model: Model,
    capabilities: Sequence[AbstractCapability] = (),
) -> StructuralAgents:
    agents = StructuralAgents(
        ontology_filter=cast(
            Agent[ConstructionValidation, OntologySelection],
            create_agent(
                ontology_model,
                name="structural_ontology_filter",
                retries=2,
                deps_type=ConstructionValidation,
                output_type=OntologySelection,
                instructions=STRUCTURAL_INSTRUCTIONS["structural_ontology_filter"],
                capabilities=capabilities,
            ),
        ),
        selector=cast(
            Agent[ConstructionValidation, PieceSelection],
            create_agent(
                selection_model,
                name="structural_selector",
                retries=2,
                deps_type=ConstructionValidation,
                output_type=PieceSelection,
                instructions=STRUCTURAL_INSTRUCTIONS["structural_selector"],
                capabilities=capabilities,
            ),
        ),
        wiring=cast(
            Agent[ConstructionValidation, SemanticWiring],
            create_agent(
                wiring_model,
                name="structural_wiring",
                retries=2,
                deps_type=ConstructionValidation,
                output_type=SemanticWiring,
                instructions=STRUCTURAL_INSTRUCTIONS["structural_wiring"],
                capabilities=capabilities,
            ),
        ),
        binder=cast(
            Agent[ConstructionValidation, PositionalBindings],
            create_agent(
                binding_model,
                name="structural_binder",
                retries=2,
                deps_type=ConstructionValidation,
                output_type=PositionalBindings,
                instructions=STRUCTURAL_INSTRUCTIONS["structural_binder"],
                capabilities=capabilities,
            ),
        ),
    )
    for agent in (
        agents.ontology_filter,
        agents.selector,
        agents.wiring,
        agents.binder,
    ):
        agent.output_validator(_validated_output)
    return agents


class Neo4jStructuralRetriever:
    def __init__(
        self, driver: AsyncDriver, *, agents: StructuralAgents, database: str = "neo4j"
    ) -> None:
        self.driver = driver
        self.agents = agents
        self.database = database

    async def retrieve(
        self,
        request: RetrievalRequest,
        *,
        deadline: float,
        usage: RunUsage | None = None,
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
            "hop_bound",
        ] = "schema_filtering"
        attempts = 0
        caller_usage = usage
        branch_usage = RunUsage()
        stage_start = 0
        validation = ConstructionValidation(filtered_catalog, "schema_filtering")
        try:
            _remaining(deadline)
            async with asyncio.timeout_at(deadline):
                attempts = 1
                question = request.rewrite.question
                with _stage(
                    "schema_filtering",
                    validation=validation,
                    usage=branch_usage,
                    deadline=deadline,
                ) as span:
                    await self.agents.ontology_filter.run(
                        json.dumps(
                            {
                                "question": question,
                                "catalog": public_pieces(CATALOG),
                            }
                        ),
                        usage=branch_usage,
                        deps=validation,
                    )
                    catalog = cast(tuple[Piece, ...], validation.result)
                    if span is not None:
                        span.set_attribute("accepted_pieces", public_pieces(catalog))
                stage = "typed_selection"
                stage_start = branch_usage.requests
                validation = ConstructionValidation(
                    lambda output: selected_pieces(output, catalog), stage
                )
                with _stage(
                    "typed_selection",
                    validation=validation,
                    usage=branch_usage,
                    deadline=deadline,
                ) as span:
                    await self.agents.selector.run(
                        json.dumps(
                            {
                                "question": question,
                                "catalog": public_pieces(catalog),
                            }
                        ),
                        usage=branch_usage,
                        deps=validation,
                    )
                    pieces = cast(dict[str, tuple[Piece, ...]], validation.result)
                    chosen = {
                        kind: public_pieces(items) for kind, items in pieces.items()
                    }
                    if span is not None:
                        span.set_attribute("accepted_pieces", chosen)
                stage = "wiring"
                stage_start = branch_usage.requests
                validation = ConstructionValidation(
                    lambda output: validate_wiring(output, pieces), stage
                )
                with _stage(
                    "wiring",
                    validation=validation,
                    usage=branch_usage,
                    deadline=deadline,
                ) as span:
                    wiring = (
                        await self.agents.wiring.run(
                            json.dumps({"question": question, "pieces": chosen}),
                            usage=branch_usage,
                            deps=validation,
                        )
                    ).output
                    if span is not None:
                        span.set_attribute("wiring", wiring.model_dump(mode="json"))
                stage = "binding"
                stage_start = branch_usage.requests
                validation = ConstructionValidation(
                    lambda output: compile_query(pieces, wiring, output), "validation"
                )
                with _stage(
                    "binding",
                    validation=validation,
                    usage=branch_usage,
                    deadline=deadline,
                ) as span:
                    binding = await self.agents.binder.run(
                        json.dumps(
                            {
                                "question": question,
                                "filters": [
                                    {
                                        **public_pieces(
                                            (pieces["filter"][item.filter_index],)
                                        )[0],
                                        "slot_index": index,
                                        "role_index": item.role_index,
                                    }
                                    for index, item in enumerate(wiring.filters)
                                ],
                                "wiring": wiring.model_dump(),
                                "pieces": chosen,
                            }
                        ),
                        usage=branch_usage,
                        deps=validation,
                    )
                    if span is not None:
                        span.set_attribute(
                            "bindings", binding.output.model_dump(mode="json")
                        )
                stage = "validation"
                cypher, parameters = cast(tuple[str, dict[str, str]], validation.result)
                stage = "cypher_execution"
                stage_start = branch_usage.requests
                with _stage("cypher_execution", deadline=deadline) as span:
                    if span is not None:
                        span.set_attribute("database", self.database)
                    async with self.driver.session(
                        database=self.database, default_access_mode=READ_ACCESS
                    ) as session:
                        result = await session.run(
                            Query(
                                cast(LiteralString, cypher),
                                timeout=_remaining(deadline),
                            ),
                            parameters=parameters,
                        )
                        rows = await result.data()
                    if span is not None:
                        span.set_attribute("row_count", len(rows))
                stage = "hydration"
                with _stage("hydration", deadline=deadline) as span:
                    outcome = SuccessfulBranch(
                        branch=RetrievalBranch.STRUCTURAL,
                        candidates=tuple(
                            BranchCandidate(
                                chunk_id=row["chunk_id"],
                                source_article_id=row["source_article_id"],
                                ranking=BranchRanking(
                                    branch=RetrievalBranch.STRUCTURAL,
                                    rank=rank,
                                    score=None,
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
                    if span is not None:
                        span.set_attribute("candidate_count", len(outcome.candidates))
                return outcome
        except TimeoutError:
            stage, kind = "deadline", "deadline_exhausted"
        except (ModelAPIError, httpx.TransportError):
            kind = "transport"
        except UnexpectedModelBehavior:
            kind = "model_output"
            if validation.rejected_request == branch_usage.requests:
                stage, kind = validation.stage, "validation"
                if validation.hop_bound:
                    stage, kind = "hop_bound", "hop_bound_exhausted"
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
            if caller_usage is not None:
                caller_usage.incr(branch_usage)
            if attempts:
                attempts = max(1, branch_usage.requests - stage_start)
            logger.info(
                "retrieval_model_usage",
                extra={
                    "event": "retrieval_model_usage",
                    "branch": "structural",
                    "requests": branch_usage.requests,
                    "input_tokens": branch_usage.input_tokens,
                    "output_tokens": branch_usage.output_tokens,
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
    record_branch_failure(diagnostic)
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
    return tuple(
        _claim(claim, piece)
        for claim, piece in zip(row["claims"], pieces["relationship"], strict=True)
    )


def _claim(row, piece) -> GraphClaim:
    props = row["claim_properties"]
    article_level = piece.predicate in {"ABOUT_TOPIC", "DISCUSSES_TOPIC"}
    return GraphClaim(
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
        source_article_ids=tuple(props.get("articles", ())) if article_level else (),
        needs_review=props.get("needs_review", False),
    )
