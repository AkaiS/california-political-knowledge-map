"""Entity Extraction as an evaluated task.

Cases come from `evals/silver/extraction.yaml`, authored elsewhere and only
read here.  It is silver, not gold: labeled by `claude-opus-5` against
`docs/evaluation/extraction-annotation.md`, so a run measures agreement with
that annotator and a claim both it and the model miss scores as a pass.

A case is one Article Chunk, cut from a Story whose accepted silver Mention
Spans were already substituted.  That is what extraction sees in production
-- never the article, never the chunk's overlap context -- so it is what a
case holds.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic_evals.evaluators import Evaluator, EvaluatorContext

from knowledge_map.adapters.extraction import (
    ExtractionError,
    PydanticAIEntityExtractionAdapter,
    get_extraction_agent,
    load_instructions,
)
from knowledge_map.schemas import (
    ExtractionResult,
    ModelDeployment,
    Node,
    Relationship,
)

from ..deployment import as_deployment, default_model
from ..scoring import UNSCORED, detection_scores
from .registry import EvaluationTask, register


class ExtractionInput(BaseModel):
    """One Article Chunk as the Entity Extraction agent sees it.

    The agent is shown `text` alone; `url`, `title` and `chunk_index` are
    carried so a report names something a person can open.
    """

    model_config = ConfigDict(extra="forbid")

    url: str
    title: str
    chunk_index: int
    text: str


class ExtractionExpectation(BaseModel):
    """The silver nodes and relationships retained for one Article Chunk."""

    model_config = ConfigDict(extra="forbid")

    nodes: list[Node] = Field(default_factory=list)
    relationships: list[Relationship] = Field(default_factory=list)


class ExtractionOutput(BaseModel):
    """What one extraction attempt produced, including its own failure.

    A failed extraction is scored as a zero rather than raised, so it stays
    in the population.
    """

    model_config = ConfigDict(extra="forbid")

    nodes: list[Node] = Field(default_factory=list)
    relationships: list[Relationship] = Field(default_factory=list)
    dropped_item_count: int = 0
    """How many items conformance refused before the rest were returned.

    Off-ontology output never reaches the other scores -- conformance has
    already removed it -- so without this the report cannot tell a model
    that stayed inside the News Ontology from one that was trimmed back
    into it.
    """
    failure_type: str | None = None


class ExtractionSilverMetadata(BaseModel):
    """Source and model provenance for one silver-labeled Article Chunk.

    ``coreference_silver_set`` names the file the chunk's resolved text came
    from, because re-cutting these chunks from a later revision of that file
    would silently change what every case is asking about.
    """

    model_config = ConfigDict(extra="forbid")

    source_table: Literal["stories"]
    story_id: int
    chunk_index: int
    chunk_count: int
    label_quality: Literal["silver"]
    annotator_model: str
    annotation_guideline: str
    coreference_silver_set: str


def _dropped_item_count(adapter: PydanticAIEntityExtractionAdapter) -> int:
    """Total drops the adapter recorded for the one chunk it just ran."""

    return sum(
        item.count
        for entries in adapter.adherence_report.root.values()
        for item in entries.values()
    )


def build_task(model: str | ModelDeployment, data_set: Any) -> Any:
    """Return the callable one case is run through, bound to a deployment.

    `data_set` is in the signature for the registry's uniform call and goes
    unused; nothing here few-shots.  The agent is built once and each case
    gets its own adapter, because the Adherence Report is per-chunk state
    and `--max-concurrency` runs cases side by side.
    """

    del data_set

    deployment = as_deployment(model)
    agent = get_extraction_agent(deployment)

    def extract(case_input: ExtractionInput) -> ExtractionOutput:
        adapter = PydanticAIEntityExtractionAdapter(agent=agent)
        try:
            result = adapter.extract(case_input.text)
        except ExtractionError as error:
            return ExtractionOutput(
                dropped_item_count=_dropped_item_count(adapter),
                failure_type=error.failure_type,
            )
        return ExtractionOutput(
            nodes=result.nodes,
            relationships=result.relationships,
            dropped_item_count=_dropped_item_count(adapter),
        )

    return extract


def normalize_name(name: str) -> str:
    """Fold case and collapse whitespace, and change nothing else.

    A shortened name stays a mismatch here: `Newsom` is not `Gavin Newsom`,
    and nothing in this report pretends otherwise.
    """

    return " ".join(name.split()).casefold()


NodeIdentity = tuple[str, str]
RelationshipIdentity = tuple[str, str, str]


def node_identity(node: Node) -> NodeIdentity:
    """A node's identity in this report: its folded name and its label.

    The same pair persistence keys on, so two nodes this report calls one
    node are one node in the graph.
    """

    return (normalize_name(node.name), node.label)


def relationship_identity(relationship: Relationship) -> RelationshipIdentity:
    """A claim's identity: its two folded endpoint names and its type.

    Endpoint labels are left out deliberately.  A mislabeled endpoint is
    already counted against `FoundTheSilverNodes`, and counting it twice
    would make one mistake look like two.
    """

    return (
        normalize_name(relationship.source),
        relationship.relationship_type,
        normalize_name(relationship.target),
    )


def _by_identity(items: Sequence[Any], identity: Any) -> dict[Any, Any]:
    """Index items by identity, last one winning, as persistence merges them."""

    return {identity(item): item for item in items}


class FoundTheSilverNodes(Evaluator):
    """The same entities were named, under the same labels.

    Read recall first: an entity extraction never proposed is absent from
    the graph, while a spurious one is a node nothing else connects to.
    A chunk silver left empty scores zero precision the moment the model
    invents anything, and a perfect 1.0 on both when it also returns none.
    """

    def evaluate(self, ctx: EvaluatorContext) -> Mapping[str, float]:
        expected = {node_identity(node) for node in ctx.expected_output.nodes}
        found = {node_identity(node) for node in ctx.output.nodes}
        if not expected and not found:
            return {"node_precision": 1.0, "node_recall": 1.0, "node_f1": 1.0}
        return detection_scores(expected, found, "node")


class AgreedOnTheNodeDetail(Evaluator):
    """Of the nodes both named, how many carry the same detail.

    Conditional on detection, and reported as two independent scores: the
    sub-labels, which the ontology closes, and the properties, which it
    only permits.  Either key is absent when nothing was comparable --
    almost every silver node declares no properties at all, so
    `node_property_accuracy` speaks for a handful of cases and is read as
    such.

    Nothing comparable is `UNSCORED`, never `None` -- see
    `knowledge_map.evaluation.scoring`.
    """

    def evaluate(self, ctx: EvaluatorContext) -> Mapping[str, float]:
        expected = _by_identity(ctx.expected_output.nodes, node_identity)
        found = _by_identity(ctx.output.nodes, node_identity)
        shared = expected.keys() & found.keys()
        if not shared:
            return UNSCORED

        scores: dict[str, float] = {
            "sub_label_accuracy": sum(
                set(expected[key].sub_labels) == set(found[key].sub_labels)
                for key in shared
            )
            / len(shared)
        }

        with_properties = [key for key in shared if expected[key].properties]
        if with_properties:
            scores["node_property_accuracy"] = sum(
                expected[key].properties == found[key].properties
                for key in with_properties
            ) / len(with_properties)
        return scores


class FoundTheSilverRelationships(Evaluator):
    """The same claims were made between the same entities.

    A claim whose endpoints were never extracted cannot be made at all, so
    this score is bounded by `FoundTheSilverNodes`; read the two together
    before blaming the model's relationship judgment.
    """

    def evaluate(self, ctx: EvaluatorContext) -> Mapping[str, float]:
        expected = {
            relationship_identity(item) for item in ctx.expected_output.relationships
        }
        found = {relationship_identity(item) for item in ctx.output.relationships}
        if not expected and not found:
            return {
                "relationship_precision": 1.0,
                "relationship_recall": 1.0,
                "relationship_f1": 1.0,
            }
        return detection_scores(expected, found, "relationship")


class AgreedOnTheClaimProperties(Evaluator):
    """Of the claims both made, how many agree on the Claim Key values.

    Scored over the claims silver gave a property at all -- a stance's
    alignment, a contribution's amount -- because that value is what
    distinguishes two edges of one type between one pair.  Scores nothing
    when no shared claim carried one.
    """

    def evaluate(self, ctx: EvaluatorContext) -> Mapping[str, float]:
        expected = _by_identity(
            ctx.expected_output.relationships, relationship_identity
        )
        found = _by_identity(ctx.output.relationships, relationship_identity)
        shared = [
            key for key in expected.keys() & found.keys() if expected[key].properties
        ]
        if not shared:
            return UNSCORED
        agreed = sum(
            expected[key].properties == found[key].properties for key in shared
        )
        return {"claim_property_accuracy": agreed / len(shared)}


class StayedInsideTheNewsOntology(Evaluator):
    """Nothing the model emitted had to be conformed away.

    The other scores read the conformed result, so an invented label or
    relationship type is invisible to them -- it was already dropped.  This
    is the only place a run says the model was writing outside the ontology.
    """

    def evaluate(self, ctx: EvaluatorContext) -> bool:
        return ctx.output.dropped_item_count == 0


class ExtractedWithoutFailing(Evaluator):
    """The run produced an Extraction Result instead of raising.

    Read alongside the others to tell a run that failed outright from one
    that answered badly; both score zero there.
    """

    def evaluate(self, ctx: EvaluatorContext) -> bool:
        return ctx.output.failure_type is None


EXTRACTION_TASK = register(
    EvaluationTask(
        name="extraction",
        input_type=ExtractionInput,
        output_type=ExtractionExpectation,
        metadata_type=ExtractionSilverMetadata,
        build=build_task,
        evaluators=(
            FoundTheSilverNodes(),
            AgreedOnTheNodeDetail(),
            FoundTheSilverRelationships(),
            AgreedOnTheClaimProperties(),
            StayedInsideTheNewsOntology(),
            ExtractedWithoutFailing(),
        ),
        default_model=default_model(),
        collect=None,
        # Digested after the ontology is rendered into it, because a run
        # whose ontology changed is not a run of the same prompt.
        prompts=lambda: {"extraction": load_instructions()},
    )
)


def silver_extraction_result(expectation: ExtractionExpectation) -> ExtractionResult:
    """The expected output as the Extraction Result it stands for.

    Lets a caller run the silver labels through the same conformance the
    adapter applies to a model's answer.
    """

    return ExtractionResult(
        nodes=list(expectation.nodes), relationships=list(expectation.relationships)
    )
