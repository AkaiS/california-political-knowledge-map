"""Article-level Policy Area results as they cross the Graph Database Adapter.

A Policy Area is a property of a Source Article's discussion rather than of a
sentence, so both halves of it are decided once per article and handed to the
write path together: the areas the article discusses, and the assignments from
the measures it names to those areas.

A Topic Assignment names its measure by the surface string extraction produced,
which is what lets the write path resolve the measure's node exactly as the
chunk extraction write does — including a Bill whose Bill Session Resolution
supplied its key.
"""

import logging
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from knowledge_map.ontology import news

logger = logging.getLogger(__name__)

#: The closed vocabulary as the classification stage offers it to a model: one
#: string per Policy Area, its canonical name, which is also how the write path
#: keys the node.
POLICY_AREA_NAMES: tuple[str, ...] = tuple(area.name for area in news.POLICY_AREAS)

#: The vocabulary as a type, for the Data Sets and reports that must fail on a
#: name the write path could never key rather than score a silent zero.
PolicyAreaName = Literal[POLICY_AREA_NAMES]  # type: ignore[valid-type]

#: The `ABOUT_TOPIC` source labels: the measures a Policy Area can be the topic
#: of.  Read from the News Ontology rather than restated, so a measure label
#: added there is not one this schema silently rejects.
MEASURE_LABELS: frozenset[str] = news.RELATIONSHIPS["ABOUT_TOPIC"].source_labels

MeasureLabel = Literal[tuple(sorted(MEASURE_LABELS))]  # type: ignore[valid-type]


class PolicyAreaClassification(BaseModel):
    """The Policy Areas one Source Article discusses.

    Only members of the vocabulary become areas: a name it does not declare is
    dropped, and the rest of the answer stands, because an article needs no
    Policy Area to reach the graph — an article the vocabulary does not cover
    classifies to nothing rather than to a nearest miss, and one whose answer
    was partly off-vocabulary keeps the part that was not.

    No maximum is set: the Silver Set records the distribution before any limit
    is drawn from it.
    """

    policy_areas: list[str] = Field(default_factory=list)

    @field_validator("policy_areas")
    @classmethod
    def _keep_only_vocabulary_members(cls, areas: list[str]) -> list[str]:
        kept: list[str] = []
        dropped: list[str] = []
        for area in areas:
            if area in POLICY_AREA_NAMES:
                if area not in kept:
                    kept.append(area)
            elif area not in dropped:
                dropped.append(area)
        if dropped:
            # Named, not counted: a model drifting off the vocabulary reads as
            # a model finding fewer areas unless what it answered is on record.
            logger.warning(
                "Dropped %d answer(s) outside the Policy Area vocabulary: %s",
                len(dropped),
                ", ".join(dropped),
            )
        return kept


class TopicAssignment(BaseModel):
    """One measure named in a Source Article, and the Policy Area it is about."""

    #: The measure's surface string, as extraction produced it.
    measure_name: str = Field(..., min_length=1)
    #: The measures an `ABOUT_TOPIC` edge may start from.
    measure_label: MeasureLabel
    #: The canonical name of the Policy Area, which is how the node is keyed.
    policy_area: str = Field(..., min_length=1)


class TopicAssignments(BaseModel):
    """Every measure-to-area assignment one Source Article supports.

    An assignment is not marked with how it was arrived at.  A declared
    relationship property joins that relationship's Claim Key, so two edges
    differing only in their provenance would become two claims about one pair.
    """

    assignments: list[TopicAssignment] = Field(default_factory=list)
