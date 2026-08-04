"""Status vocabularies owned by the relevance and validation stages.

`RelevanceStatus` and `ValidationStatus` both carry a `PENDING` member, but they
are separate state machines writing separate columns of `scraped_html_cache`.
Keeping them as distinct types is what stops one stage's state reaching the
other stage's column.

Member order matches the `CHECK` constraints these enums render, so the
generated DDL is textually identical to what it replaced.
"""

from enum import Enum


class RelevanceStatus(str, Enum):
    """Where an article sits in the relevance classification stage."""

    RELEVANT = "RELEVANT"
    IRRELEVANT = "IRRELEVANT"
    INCONCLUSIVE = "INCONCLUSIVE"
    PENDING = "PENDING"


class ValidationStatus(str, Enum):
    """Where an article sits in the extraction/validation stage."""

    PENDING = "PENDING"
    VALIDATED = "VALIDATED"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    UNVALIDATABLE = "UNVALIDATABLE"


class LabelSource(str, Enum):
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
