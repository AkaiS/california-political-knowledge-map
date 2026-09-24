"""Typed semantic construction followed by read-only Neo4j retrieval."""

import asyncio
import json
import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, LiteralString, cast

import httpx
from neo4j import READ_ACCESS, AsyncDriver, Query
from neo4j.exceptions import DriverError, Neo4jError
from pydantic import JsonValue
from pydantic_ai import Agent, ModelRetry, RunContext
from pydantic_ai.exceptions import ModelAPIError, UnexpectedModelBehavior
from pydantic_ai.models import Model
from pydantic_ai.usage import RunUsage

from knowledge_map.core.audit import (
    AuditStage,
    child_audit_stage,
    dispatch_audit_stage,
    observe_audit_metadata,
    observe_retrieval_failure,
)
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


@contextmanager
def _observe_stage(
    name: str,
    deadline: float,
    usage: RunUsage | None = None,
    validation: "ConstructionValidation | None" = None,
) -> Iterator[AuditStage]:
    requests, input_tokens, output_tokens = (
        (usage.requests, usage.input_tokens, usage.output_tokens)
        if usage is not None
        else (0, 0, 0)
    )
    with child_audit_stage(f"structural_{name}") as observation:
        try:
            yield observation
        except BaseException as error:
            kind = "unexpected"
            if isinstance(error, asyncio.CancelledError):
                kind = (
                    "deadline_exhausted"
                    if asyncio.get_running_loop().time() >= deadline
                    else "cancelled"
                )
            elif isinstance(error, TimeoutError):
                kind = "deadline_exhausted"
            elif isinstance(error, (ModelAPIError, httpx.TransportError)):
                kind = "transport"
            elif isinstance(error, UnexpectedModelBehavior):
                kind = "model_output"
                if (
                    validation is not None
                    and usage is not None
                    and validation.rejected_request == usage.requests
                ):
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
            elif isinstance(error, (KeyError, TypeError, ValueError)):
                kind = "hydration" if name == "hydration" else "validation"
            observation.metadata.update(
                failure_stage=name,
                failure_kind=kind,
                diagnostic="Structural retrieval could not complete this stage.",
            )
            raise
        finally:
            if usage is not None:
                observation.metadata["usage"] = {
                    "requests": usage.requests - requests,
                    "input_tokens": usage.input_tokens - input_tokens,
                    "output_tokens": usage.output_tokens - output_tokens,
                }
            if name == "binding" and validation is not None:
                validation.dispatch_query_observation()


@dataclass
class ConstructionValidation:
    check: Callable[[Any], object]
    stage: Literal["schema_filtering", "typed_selection", "wiring", "validation"]
    rejected_request: int = -1
    hop_bound: bool = False
    result: object | None = None
    query_started_at: datetime | None = None
    query_ended_at: datetime | None = None
    query_failure_kind: str | None = None

    def dispatch_query_observation(self) -> None:
        if self.query_started_at is None or self.query_ended_at is None:
            return
        metadata: dict[str, JsonValue]
        if self.query_failure_kind is None:
            cypher, parameters = cast(tuple[str, dict[str, str]], self.result)
            metadata = {"query": cypher, "parameters": dict(parameters)}
        else:
            metadata = {
                "failure_stage": "validation",
                "failure_kind": self.query_failure_kind,
                "diagnostic": "Structural retrieval could not complete this stage.",
            }
        dispatch_audit_stage(
            "structural_validation",
            started_at=self.query_started_at,
            ended_at=self.query_ended_at,
            status="succeeded" if self.query_failure_kind is None else "failed",
            metadata=metadata,
        )


def _validated_output(ctx: RunContext[ConstructionValidation], output: Any) -> Any:
    if ctx.deps.stage == "validation":
        ctx.deps.query_started_at = datetime.now(UTC)
        ctx.deps.query_failure_kind = "unexpected"
    try:
        ctx.deps.result = ctx.deps.check(output)
        ctx.deps.query_failure_kind = None
    except ValueError as error:
        ctx.deps.query_failure_kind = "validation"
        ctx.deps.rejected_request = ctx.usage.requests
        ctx.deps.hop_bound = isinstance(error, HopBoundError)
        raise ModelRetry(str(error)) from error
    finally:
        if ctx.deps.stage == "validation":
            ctx.deps.query_ended_at = datetime.now(UTC)
    return output


@dataclass(frozen=True)
class StructuralAgents:
    ontology_filter: Agent[ConstructionValidation, OntologySelection]
    selector: Agent[ConstructionValidation, PieceSelection]
    wiring: Agent[ConstructionValidation, SemanticWiring]
    binder: Agent[ConstructionValidation, PositionalBindings]


_STRUCTURAL_COMMON = (
    "Use only the approved question and supplied semantic choices. "
    "Never emit Cypher, graph identifiers, variables, parameters, projections, or provenance paths. "
)
STRUCTURAL_INSTRUCTIONS = {
    "structural_ontology_filter": _STRUCTURAL_COMMON
    + "Select relevant labels, relationships, and filter properties.",
    "structural_selector": _STRUCTURAL_COMMON
    + "Select only supplied piece IDs, keeping separate occurrences for each role. "
    "For a same-reporting-chunk question, select the requested result entity first, "
    "the named entity second, and an optional Source Article third; select no "
    "question-semantic relationship for those fixed provenance paths.",
    "structural_wiring": _STRUCTURAL_COMMON
    + "Wire selected occurrences by zero-based numeric index. Use each filter and relationship once. "
    "Use distinct_roles for questions asking for other or different entities. "
    "A same-reporting-chunk question has no triples; wire its entity and optional "
    "Source Article filters to the selected roles.",
    "structural_binder": _STRUCTURAL_COMMON
    + "Return question values in supplied filter order. Preserve Bill names for deterministic parsing. "
    "When several filters bind Bill names, put null in those positional values and supply "
    "one bill_names assignment with slot_index and value for each. Assign each bill to its "
    "wired role; never repeat one designation across the slots. Other values remain positional.",
}


def get_structural_agents(
    *,
    ontology_model: Model,
    selection_model: Model,
    wiring_model: Model,
    binding_model: Model,
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
                with _observe_stage(
                    stage, deadline, branch_usage, validation
                ) as observation:
                    selection = await self.agents.ontology_filter.run(
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
                    observation.metadata["selection"] = selection.output.model_dump(
                        mode="json"
                    )
                stage = "typed_selection"
                stage_start = branch_usage.requests
                validation = ConstructionValidation(
                    lambda output: selected_pieces(output, catalog), stage
                )
                with _observe_stage(
                    stage, deadline, branch_usage, validation
                ) as observation:
                    selection = await self.agents.selector.run(
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
                    observation.metadata["selection"] = selection.output.model_dump(
                        mode="json"
                    )
                chosen = {kind: public_pieces(items) for kind, items in pieces.items()}
                stage = "wiring"
                stage_start = branch_usage.requests
                validation = ConstructionValidation(
                    lambda output: validate_wiring(output, pieces), stage
                )
                with _observe_stage(
                    stage, deadline, branch_usage, validation
                ) as observation:
                    wiring = (
                        await self.agents.wiring.run(
                            json.dumps({"question": question, "pieces": chosen}),
                            usage=branch_usage,
                            deps=validation,
                        )
                    ).output
                    observation.metadata["wiring"] = wiring.model_dump(mode="json")
                stage = "binding"
                stage_start = branch_usage.requests
                validation = ConstructionValidation(
                    lambda output: compile_query(pieces, wiring, output), "validation"
                )
                with _observe_stage(
                    stage, deadline, branch_usage, validation
                ) as observation:
                    bindings = await self.agents.binder.run(
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
                    observation.metadata["bindings"] = bindings.output.model_dump(
                        mode="json"
                    )
                stage = "validation"
                cypher, parameters = cast(tuple[str, dict[str, str]], validation.result)
                stage = "cypher_execution"
                stage_start = branch_usage.requests
                with _observe_stage(stage, deadline) as observation:
                    observation.metadata["database"] = self.database
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
                    observation.metadata["returned_row_count"] = len(rows)
                stage = "hydration"
                with _observe_stage(stage, deadline) as observation:
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
                    observation.metadata["candidate_count"] = len(outcome.candidates)
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
            observe_audit_metadata(
                usage={
                    "requests": branch_usage.requests,
                    "input_tokens": branch_usage.input_tokens,
                    "output_tokens": branch_usage.output_tokens,
                }
            )
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
    observe_retrieval_failure(diagnostic)
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
