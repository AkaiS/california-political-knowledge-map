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

from typing import Literal

from pydantic import BaseModel, Field

from knowledge_map.ontology import news

#: The closed vocabulary as the classification stage offers it to a model: one
#: string per Policy Area, its canonical name, which is also how the write path
#: keys the node.  Offering the id alongside would make an area two answers a
#: model could pick between.
PolicyAreaName = Literal[tuple(area.name for area in news.POLICY_AREAS)]  # type: ignore[valid-type]


class PolicyAreaClassification(BaseModel):
    """The Policy Areas one Source Article discusses.

    No maximum is set: the Gold Set records the distribution before any limit
    is drawn from it.  An article the vocabulary does not cover classifies to
    nothing rather than to a nearest miss.
    """

    policy_areas: list[PolicyAreaName] = Field(default_factory=list)


class TopicAssignment(BaseModel):
    """One measure named in a Source Article, and the Policy Area it is about."""

    #: The measure's surface string, as extraction produced it.
    measure_name: str = Field(..., min_length=1)
    #: The `ABOUT_TOPIC` source labels the News Ontology permits.
    measure_label: Literal["Bill", "Prop"]
    #: The canonical name of the Policy Area, which is how the node is keyed.
    policy_area: str = Field(..., min_length=1)
