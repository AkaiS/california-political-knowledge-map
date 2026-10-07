"""Run staged Jev Cypher retrieval alongside sparse and dense retrieval."""

import asyncio
import json
import os
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import keyring
from CyVer.validators.properties_validator import PropertiesValidator
from CyVer.validators.schema_validator import SchemaValidator
from CyVer.validators.syntax_validator import SyntaxValidator
from neo4j import READ_ACCESS, AsyncDriver, Driver, Query, RoutingControl
from pydantic_ai import Agent
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.models import Model
from pydantic_ai.usage import RunUsage
from typesafe_sdk import TypeSafeClient

from knowledge_map.jev.binding import (
    build_binding_contract,
    validate_and_resolve_bindings,
)
from knowledge_map.jev.catalog import BY_ID, COMPILER_NEWS_ARTICLE_ROLE
from knowledge_map.jev.compiler import SemanticCompileError, compile_semantic
from knowledge_map.jev.construction import (
    _abstract_cyver,
    _binding_prompt,
    _composer_prompt,
    _deterministic_staged_wiring,
    _deterministic_unique_wiring,
    _normalize_bill_name_bindings,
    _resolve_selection,
    _semantic_wiring_from_composer,
)
from knowledge_map.jev.contracts import (
    ComposerWiring,
    PieceSelection,
    PositionalBindings,
    SemanticSchemaSelection,
)
from knowledge_map.jev.jev_schema_filter import narrow_schema
from knowledge_map.jev.reporting import select_pieces
from knowledge_map.jev.validation import Case, QueryPlan, _execute, validate_plan
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
from knowledge_map.utils.agents import create_agent

JEV_INSTRUCTIONS = {
    "jev_composer": load_prompt(
        "jev-staged/runner-composer-instructions-01", version=1
    ),
    "jev_binder": load_prompt("jev-staged/runner-binder-instructions-01", version=2),
}
SCHEMA_THRESHOLD = 0.8


def jev_client() -> TypeSafeClient:
    api_key = os.environ.get("TYPESAFE_API_KEY") or keyring.get_password(
        "jev_api", "test_key"
    )
    if not api_key:
        raise RuntimeError(
            "Set TYPESAFE_API_KEY or configure Keychain service jev_api, account test_key."
        )
    return TypeSafeClient(api_key=api_key, timeout=30)


@dataclass(frozen=True)
class JevAgents:
    composer: Agent
    binder: Agent


def get_jev_agents(
    model: Model, *, capabilities: Sequence[AbstractCapability] = ()
) -> JevAgents:
    return JevAgents(
        create_agent(
            model,
            name="jev_composer",
            output_type=ComposerWiring,
            instructions=JEV_INSTRUCTIONS["jev_composer"],
            retries=2,
            capabilities=capabilities,
        ),
        create_agent(
            model,
            name="jev_binder",
            output_type=PositionalBindings,
            instructions=JEV_INSTRUCTIONS["jev_binder"],
            retries=2,
            capabilities=capabilities,
        ),
    )


class ReadGraph(Driver):
    """CyVer requires a Driver; constrain its queries to this database and deadline."""

    def __init__(self, driver, database, deadline):
        self._driver, self._database, self._deadline = driver, database, deadline

    def session(self, **kwargs):
        return self._driver.session(
            **{**kwargs, "database": self._database, "default_access_mode": READ_ACCESS}
        )

    def execute_query(self, query_, parameters_=None, **kwargs):
        # CyVer emits plain query strings without a timeout or read routing.
        timeout = max(0.001, self._deadline - time.monotonic())
        return self._driver.execute_query(
            Query(str(query_), timeout=timeout),
            parameters_,
            **{**kwargs, "database_": self._database, "routing_": RoutingControl.READ},
        )

    def close(self):
        pass


def _safe_audit(value):
    """Keep decisions and model inputs, omit provider exception payloads."""
    if isinstance(value, dict):
        return {
            key: (
                "Stage failed."
                if key == "error" and item
                else ["Selection validation failed."]
                if key == "normalization_errors" and item
                else _safe_audit(item)
            )
            for key, item in value.items()
            if key != "model_visible_prompt"
        }
    if isinstance(value, (list, tuple)):
        return [_safe_audit(item) for item in value]
    return value


class JevStructuralRetriever:
    def __init__(
        self,
        driver: AsyncDriver,
        *,
        sync_driver: Driver,
        client: TypeSafeClient,
        agents: JevAgents,
        database: str = "neo4j",
    ):
        self.driver, self.sync_driver, self.client = driver, sync_driver, client
        self.agents, self.database = agents, database

    async def retrieve(
        self,
        request: RetrievalRequest,
        *,
        deadline: float,
        usage: RunUsage | None = None,
    ) -> SuccessfulBranch | FailedBranch:
        stage = "schema_filtering"
        audit: dict[str, Any] = {
            "backend": "jev-staged",
            "schema_threshold": SCHEMA_THRESHOLD,
        }
        local_usage = RunUsage()
        case = Case("chat", "chat", request.rewrite.question)
        graph = ReadGraph(self.sync_driver, self.database, deadline)
        try:
            async with asyncio.timeout_at(deadline):
                with structural_stage(stage) as span:
                    narrowed = await asyncio.to_thread(
                        narrow_schema,
                        self.client,
                        case.question,
                        threshold=SCHEMA_THRESHOLD,
                    )
                    audit["schema"] = _safe_audit(narrowed)
                    audit["schema"]["request"] = json.loads(
                        narrowed["model_visible_prompt"]
                    )
                    self._jev_usage(narrowed, local_usage)
                    if span is not None:
                        span.set_attributes(audit["schema"])
                    if not narrowed["ok"]:
                        raise ValueError("Jev schema selection failed")
                stage = "typed_selection"
                with structural_stage(stage) as span:
                    selected = await asyncio.to_thread(
                        select_pieces,
                        self.client,
                        case.question,
                        SemanticSchemaSelection.model_validate(narrowed["output"]),
                    )
                    audit["selection"] = _safe_audit(selected)
                    self._jev_usage(selected, local_usage)
                    if span is not None:
                        span.set_attributes(audit["selection"])
                    if not selected["ok"]:
                        raise ValueError("Jev role selection failed")
                    selection = PieceSelection.model_validate(selected["output"])
                    grouped, errors = _resolve_selection(
                        selection, allow_parent_roles=True
                    )
                    grouped["role_constraint"] = [
                        BY_ID[pid] for pid in selection.role_constraint_ids
                    ]
                    if errors:
                        raise ValueError("Invalid selected pieces")
                stage = "wiring"
                validators = await asyncio.to_thread(self._validators, graph)
                compiled = await self._compose(
                    case, grouped, selected, validators, local_usage
                )
                audit["cypher"] = compiled.cypher
                audit["wiring"] = compiled.wiring.model_dump(mode="json")
                stage = "binding"
                parameters, binding_audit = await self._bind(
                    case, graph, compiled, local_usage
                )
                audit["binding"] = binding_audit
                stage = "validation"
                plan = QueryPlan(
                    cypher=compiled.cypher,
                    parameters=parameters,
                    explanation="Jev-selected deterministic query",
                )
                with structural_stage(stage) as span:
                    validation = await asyncio.to_thread(
                        validate_plan,
                        graph,
                        validators,
                        plan,
                        self._remaining(deadline),
                    )
                    audit["validation"] = _safe_audit(validation)
                    if span is not None:
                        span.set_attributes(audit["validation"])
                    if not validation["authorized"]:
                        raise ValueError("CyVer rejected the bound query")
                stage = "cypher_execution"
                with structural_stage(stage) as span:
                    execution = await asyncio.to_thread(
                        _execute, graph, plan, self._remaining(deadline)
                    )
                    if not execution["ok"]:
                        raise ValueError("Read-only graph execution failed")
                    rows = execution["rows"]
                    if span is not None:
                        span.set_attribute("row_count", len(rows))
                stage = "hydration"
                with structural_stage(stage):
                    candidates = await self._candidates(
                        rows, compiled.wiring, grouped, deadline
                    )
                return SuccessfulBranch(
                    branch=RetrievalBranch.STRUCTURAL,
                    candidates=candidates,
                    construction=audit,
                    semantic_results=tuple(
                        {
                            "evidence_chunk_ids": sorted(
                                {
                                    cid
                                    for group in row.get("evidence_groups", [])
                                    for cid in group["ids"]
                                }
                            ),
                            **{
                                k: v
                                for k, v in row.items()
                                if k
                                not in {
                                    "hydrated_evidence",
                                    "hydrated_chunks",
                                    "evidence_groups",
                                    "article_properties",
                                }
                            },
                        }
                        for row in rows
                    ),
                )
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - Preserve sparse and dense evidence on Jev failure.
            kind = (
                "deadline_exhausted"
                if isinstance(error, TimeoutError)
                else "validation"
            )
            if kind == "deadline_exhausted":
                stage = "deadline"
            diagnostic = RetrievalFailureLog(
                branch=RetrievalBranch.STRUCTURAL,
                stage=stage,
                failure_kind=kind,
                attempts_consumed=local_usage.requests,
                safe_diagnostic="Jev Cypher retrieval could not complete this stage.",
            )
            record_branch_failure(diagnostic)
            audit["failure"] = diagnostic.model_dump(mode="json")
            return FailedBranch(branch=RetrievalBranch.STRUCTURAL, construction=audit)
        finally:
            if usage is not None:
                usage.incr(local_usage)

    @staticmethod
    def _remaining(deadline):
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise TimeoutError
        return remaining

    @staticmethod
    def _jev_usage(call, usage):
        counts = call.get("usage", {})
        usage.incr(
            RunUsage(
                requests=counts.get("requests", 0),
                input_tokens=counts.get("input_tokens", 0),
                output_tokens=counts.get("output_tokens", 0),
            )
        )

    @staticmethod
    def _validators(graph):
        return (
            SyntaxValidator(graph),
            SchemaValidator(graph),
            PropertiesValidator(graph),
        )

    async def _compose(self, case, grouped, selection, validators, usage):
        mode = selection["relationship_free_mode"]
        rules = selection.get("filter_attachment_rules", [])
        previous, feedback = None, None
        article_owned = any(
            p.piece_id == COMPILER_NEWS_ARTICLE_ROLE.piece_id for p in grouped["role"]
        )
        with structural_stage("wiring") as span:
            for _ in range(3):
                if article_owned:
                    wiring = (
                        _deterministic_staged_wiring(
                            grouped, rules[0], relationship_free_mode=mode
                        )
                        if rules
                        else None
                    )
                    if wiring is None:
                        raise SemanticCompileError(
                            "Invalid compiler-owned Article attachments"
                        )
                else:
                    previous = (
                        await self.agents.composer.run(
                            _composer_prompt(case, grouped, rules, previous, feedback),
                            usage=usage,
                        )
                    ).output
                    actual = previous.model_dump(mode="json")
                    if rules and any(
                        sorted(
                            json.dumps(item, sort_keys=True) for item in actual[field]
                        )
                        != sorted(
                            json.dumps(item, sort_keys=True) for item in rules[0][field]
                        )
                        for field in ("triples", "filters", "distinct_roles")
                    ):
                        feedback = {
                            "errors": [
                                load_prompt(
                                    "jev-staged/composer-attachment-correction",
                                    version=1,
                                )
                            ]
                        }
                        continue
                    wiring = _semantic_wiring_from_composer(previous, grouped)
                try:
                    compiled = compile_semantic(
                        wiring,
                        grouped,
                        relationship_free_mode=mode,
                        allow_parent_distinct=True,
                    )
                    validation = await asyncio.to_thread(
                        _abstract_cyver, validators, compiled.cypher
                    )
                    if validation["authorized_abstract_structure"]:
                        if span is not None:
                            span.set_attributes(
                                {
                                    "wiring": wiring.model_dump(mode="json"),
                                    "cypher": compiled.cypher,
                                }
                            )
                        return compiled
                    feedback = {"errors": validation["errors"]}
                except SemanticCompileError as error:
                    feedback = {"errors": [str(error)]}
                if article_owned:
                    break
            # The experiment permits this fallback only when labels identify unique occurrences.
            wiring = _deterministic_unique_wiring(grouped, relationship_free_mode=mode)
            if wiring is not None and not article_owned:
                compiled = compile_semantic(
                    wiring,
                    grouped,
                    relationship_free_mode=mode,
                    allow_parent_distinct=True,
                )
                validation = await asyncio.to_thread(
                    _abstract_cyver, validators, compiled.cypher
                )
                if validation["authorized_abstract_structure"]:
                    return compiled
            raise SemanticCompileError("Composition or abstract validation failed")

    async def _bind(self, case, graph, compiled, usage):
        with structural_stage("binding") as span:
            contract = await asyncio.to_thread(
                build_binding_contract, graph, compiled.binding_pattern
            )
            feedback, attempts = None, []
            for _ in range(3):
                result = await self.agents.binder.run(
                    _binding_prompt(
                        case, contract, feedback, pattern=compiled.binding_pattern
                    ),
                    usage=usage,
                )
                values = result.output.values
                normalized = None
                if len(values) != len(contract.slots):
                    feedback = {
                        "failures": [f"Expected {len(contract.slots)} ordered values"]
                    }
                else:
                    raw = {
                        slot.name: value
                        for slot, value in zip(contract.slots, values, strict=True)
                    }
                    raw, failures = _normalize_bill_name_bindings(
                        contract, raw, case.question
                    )
                    if failures:
                        feedback = {"failures": failures}
                    else:
                        normalized, feedback = await asyncio.to_thread(
                            validate_and_resolve_bindings,
                            graph,
                            contract,
                            raw,
                            compiled.binding_pattern,
                        )
                attempts.append({"values": values, "validation": feedback})
                if normalized is not None:
                    if span is not None:
                        span.set_attributes(
                            {"parameters": normalized, "attempts": attempts}
                        )
                    return normalized, {"parameters": normalized, "attempts": attempts}
            raise ValueError("Binding did not pass its contract")

    async def _candidates(self, rows, wiring, grouped, deadline):
        ids = sorted(
            {
                str(cid)
                for row in rows
                for group in row.get("evidence_groups", [])
                for cid in group["ids"]
            }
        )
        if not ids:
            if rows:
                raise ValueError("Graph results lack Grounding Evidence")
            return ()
        async with self.driver.session(
            database=self.database, default_access_mode=READ_ACCESS
        ) as session:
            result = await session.run(
                Query(
                    "MATCH (article:NewsArticle)-[:HAS_CHUNK]->(chunk:Chunk) WHERE chunk.id IN $ids "
                    "RETURN chunk.id AS chunk_id, chunk.text AS text, article.id AS source_article_id, "
                    "article.title AS title, article.published_date AS published_date ORDER BY chunk.id, article.id",
                    timeout=self._remaining(deadline),
                ),
                parameters={"ids": ids},
            )
            stored = await result.data()
        if len(stored) != len(ids) or {row["chunk_id"] for row in stored} != set(ids):
            raise ValueError("Grounding Evidence is absent or ambiguous")
        candidates = []
        for rank, stored_row in enumerate(stored, 1):
            chunk_id, article_id = (
                stored_row["chunk_id"],
                stored_row["source_article_id"],
            )
            routes = []
            for row in rows:
                groups = [
                    g for g in row.get("evidence_groups", []) if chunk_id in g["ids"]
                ]
                if not groups:
                    continue
                claims = []
                for triple in wiring.triples:
                    index = triple.relationship_index
                    if not any(
                        g["kind"] == f"semantic_relationship_{index}"
                        or g["kind"] == article_id
                        for g in groups
                    ):
                        continue

                    def reference(role_index, row=row, article_id=article_id):
                        role = grouped["role"][role_index]
                        node_id = row.get(f"role_{role_index}_id")
                        if role.node_label.value == "NewsArticle":
                            node_id = article_id
                        return GraphNodeReference(
                            id=node_id, label=role.node_label.value
                        )

                    predicate = row[f"semantic_relationship_{index}_relationship"]
                    properties = row[f"semantic_relationship_{index}_properties"]
                    article_level = predicate in {"DISCUSSES_TOPIC", "ABOUT_TOPIC"}
                    claims.append(
                        GraphClaim(
                            source=reference(triple.source_role_index),
                            target=reference(triple.target_role_index),
                            relationship_type=predicate,
                            claim_key={
                                key: properties[key]
                                for key in sorted(news.claim_key_properties(predicate))
                                if key in properties
                            },
                            needs_review=properties.get("needs_review", False),
                            chunk_ids=() if article_level else (chunk_id,),
                            source_article_ids=(article_id,) if article_level else (),
                        )
                    )
                entry_index = next(
                    (i for i in range(len(grouped["role"])) if row.get(f"role_{i}_id")),
                    None,
                )
                entry = (
                    GraphNodeReference(
                        id=row[f"role_{entry_index}_id"],
                        label=grouped["role"][entry_index].node_label.value,
                    )
                    if entry_index is not None
                    else GraphNodeReference(id=article_id, label="NewsArticle")
                )
                route = RetrievalRoute(
                    kind="typed_traversal",
                    matched_field=None,
                    entry_node=entry,
                    graph_claims=tuple(claims),
                )
                if route not in routes:
                    routes.append(route)
            candidates.append(
                BranchCandidate(
                    chunk_id=chunk_id,
                    source_article_id=article_id,
                    ranking=BranchRanking(
                        branch=RetrievalBranch.STRUCTURAL, rank=rank, score=None
                    ),
                    routes=tuple(routes),
                    grounding=GroundingEvidence(
                        chunk_id=chunk_id,
                        text=stored_row["text"],
                        citation=SourceArticleCitation(
                            source_article_id=article_id,
                            title=stored_row["title"],
                            url=article_id,
                            published_date=stored_row["published_date"],
                        ),
                    ),
                )
            )
        return tuple(candidates)
