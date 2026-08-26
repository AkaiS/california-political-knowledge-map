"""Status vocabularies owned by the relevance and validation stages.

`RelevanceStatus` and `ValidationStatus` write separate columns of
`scraped_html_cache` and stay distinct types even where their members
coincide.  Member order is load-bearing: it renders the `CHECK` constraints.
"""

from enum import Enum, StrEnum


class RelevanceStatus(StrEnum):
    """Where an article sits in the relevance classification stage."""

    RELEVANT = "RELEVANT"
    IRRELEVANT = "IRRELEVANT"
    INCONCLUSIVE = "INCONCLUSIVE"
    PENDING = "PENDING"


class ValidationStatus(StrEnum):
    """Where an article sits in the extraction/validation stage."""

    PENDING = "PENDING"
    VALIDATED = "VALIDATED"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    UNVALIDATABLE = "UNVALIDATABLE"


class LabelSource(StrEnum):
    """What produced a relevance label.

    `HUMAN` is privileged: only another human write may replace it.
    """

    KEYWORD = "KEYWORD"
    LLM = "LLM"
    HUMAN = "HUMAN"
    MODEL = "MODEL"


def sql_check_values(enum_type: type[Enum]) -> str:
    """Render an enum's members as the value list of a SQL `CHECK (... IN ...)`."""
    return ", ".join(f"'{member.value}'" for member in enum_type)
