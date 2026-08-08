"""Machine-readable primary and news ontology contracts."""

from .conformance import assert_news_ontology_conforms
from .extraction_conformance import (
    ConformanceDrop,
    ConformanceOutcome,
    conform_extraction_result,
)

__all__ = [
    "assert_news_ontology_conforms",
    "ConformanceDrop",
    "ConformanceOutcome",
    "conform_extraction_result",
]
