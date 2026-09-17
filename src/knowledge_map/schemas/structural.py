"""Semantic selections and positional values, never executable query text."""

from typing import Annotated, Literal

from pydantic import Field

from knowledge_map.schemas.retrieval import NonemptyText, RetrievalValue

type SemanticLabel = Literal[
    "Politician",
    "Organization",
    "LaborUnion",
    "PAC",
    "Bill",
    "Prop",
    "Campaign",
    "LegislativeEvent",
    "Committee",
    "NewsArticle",
    "PolicyArea",
]
type FilterProperty = Literal["id", "name", "session", "title", "published_date"]
type Position = Annotated[int, Field(strict=True, ge=0)]


class OntologySelection(RetrievalValue):
    labels: Annotated[tuple[SemanticLabel, ...], Field(min_length=1)]
    relationships: tuple[NonemptyText, ...]
    filter_properties: dict[SemanticLabel, tuple[FilterProperty, ...]]


class PieceSelection(RetrievalValue):
    role_ids: Annotated[tuple[NonemptyText, ...], Field(min_length=1, max_length=2)]
    relationship_ids: Annotated[tuple[NonemptyText, ...], Field(max_length=1)]
    filter_ids: Annotated[tuple[NonemptyText, ...], Field(max_length=8)]


class TripleWiring(RetrievalValue):
    relationship_index: Position
    source_role_index: Position
    target_role_index: Position


class FilterWiring(RetrievalValue):
    filter_index: Position
    role_index: Position


class SemanticWiring(RetrievalValue):
    triples: tuple[TripleWiring, ...]
    filters: tuple[FilterWiring, ...]


class PositionalBindings(RetrievalValue):
    values: Annotated[tuple[NonemptyText, ...], Field(max_length=8)]
