"""What Topic Assignment is given, and what of its answer reaches the graph.

Assignment is an article-level pass over the extractions, like Bill Session
Resolution beside it: it runs once, after the chunk loop, because extraction is
what discovers the measures.

The two drops here are what makes the write path safe.  An assignment names its
measure by the surface string extraction produced, and the write path matches
both of its endpoints rather than merging them, so an assignment naming a
measure or an area that is not there would write nothing at all — silently.
Dropping both cases before persistence turns that silence into a rule the
pipeline states and a test can hold it to.
"""

from knowledge_map.schemas import ExtractionResult, Node, TopicAssignment

#: The `ABOUT_TOPIC` source labels the News Ontology permits: the measures a
#: Policy Area can be the topic of.
MEASURE_LABELS = ("Bill", "Prop")


def extracted_measures(extractions: list[ExtractionResult]) -> list[Node]:
    """Every Bill and Prop the article's chunk extractions produced.

    One entry per measure rather than per mention: assignment judges the
    article, so a measure two chunks name is one measure to assign.
    """

    measures: list[Node] = []
    seen: set[tuple[str, str]] = set()
    for extraction in extractions:
        for node in extraction.nodes:
            if node.label not in MEASURE_LABELS:
                continue
            identity = (node.name, node.label)
            if identity in seen:
                continue
            seen.add(identity)
            measures.append(node)
    return measures


def supported_assignments(
    assignments: list[TopicAssignment],
    measures: list[Node],
    policy_areas: list[str],
) -> list[TopicAssignment]:
    """The assignments both stages support, in the order they were made.

    An assignment naming a measure no extraction produced, or an area outside
    the article's classified set, is dropped rather than persisted.
    """

    extracted = {(measure.name, measure.label) for measure in measures}
    classified = set(policy_areas)

    supported: list[TopicAssignment] = []
    seen: set[tuple[str, str, str]] = set()
    for assignment in assignments:
        if (assignment.measure_name, assignment.measure_label) not in extracted:
            continue
        if assignment.policy_area not in classified:
            continue
        identity = (
            assignment.measure_name,
            assignment.measure_label,
            assignment.policy_area,
        )
        if identity in seen:
            continue
        seen.add(identity)
        supported.append(assignment)
    return supported
