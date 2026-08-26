"""Repeated mentions inside one sentence reach the Coreference Critic.

The annotator resolves the first ``he`` in a sentence and stops: across a
full evaluation run it never returned an ``occurrence`` above 1, and it
missed every silver Mention Span that had one.  The sweep counts those
repeats from the article instead of asking for them again.
"""

from pydantic_ai.models.function import FunctionModel
from test_coreference import critic_response, mention_response

from knowledge_map.adapters.coreference import (
    ANNOTATOR_INSTRUCTIONS,
    CoreferenceDeps,
    PydanticAICoreferenceAdapter,
    get_annotator_agent,
    get_critic_agent,
    unclaimed_occurrences,
    validate_mention_spans,
)
from knowledge_map.schemas import MentionSpan


def located(content: str, spans: list[MentionSpan]):
    """Locate ``spans`` the way the resolution loop does before a sweep."""

    deps = CoreferenceDeps.for_content(content)
    validation = validate_mention_spans(deps.content, deps.sentences, spans)
    return deps, validation.valid_spans


def test_sweep_proposes_the_repeats_the_annotator_left_unclaimed():
    """A sentence with three ``he`` and one resolved span yields two more."""

    content = "Newsom spoke. Then he paused, he coughed and he sat down."
    deps, spans = located(
        content,
        [
            MentionSpan(
                sentence_label="2",
                mention_text="he",
                occurrence=1,
                canonical_entity_name="Gavin Newsom",
            )
        ],
    )

    proposals = unclaimed_occurrences(deps.content, deps.sentences, spans)

    assert [(p.mention_text, p.occurrence) for p in proposals] == [("he", 2), ("he", 3)]
    assert {p.canonical_entity_name for p in proposals} == {"Gavin Newsom"}


def test_sweep_counts_occurrences_case_sensitively():
    """``He`` opening a sentence does not lend its capital to a later ``he``.

    ``mention_text`` is matched exactly, so the two spellings are two
    independent occurrence counters and neither one's repeats are the
    other's.
    """

    content = "Newsom spoke. He paused and he coughed and he sat down."
    deps, spans = located(
        content,
        [
            MentionSpan(
                sentence_label="2",
                mention_text="He",
                occurrence=1,
                canonical_entity_name="Gavin Newsom",
            )
        ],
    )

    proposals = unclaimed_occurrences(deps.content, deps.sentences, spans)

    assert proposals == []


def test_sweep_ignores_a_mention_text_the_annotator_never_proposed():
    """Counting repeats is not detecting mentions.

    ``she`` appears twice and was never resolved, so proposing it here would
    be the sweep annotating rather than counting.
    """

    content = "Newsom spoke. Then he paused and he coughed while she waited and she left."
    deps, spans = located(
        content,
        [
            MentionSpan(
                sentence_label="2",
                mention_text="he",
                occurrence=1,
                canonical_entity_name="Gavin Newsom",
            )
        ],
    )

    proposals = unclaimed_occurrences(deps.content, deps.sentences, spans)

    assert [(p.mention_text, p.occurrence) for p in proposals] == [("he", 2)]


def test_sweep_proposes_nothing_when_every_occurrence_is_claimed():
    """An annotator that already numbered its repeats is left alone."""

    content = "Newsom spoke. Then he paused and he coughed."
    deps, spans = located(
        content,
        [
            MentionSpan(
                sentence_label="2",
                mention_text="he",
                occurrence=occurrence,
                canonical_entity_name="Gavin Newsom",
            )
            for occurrence in (1, 2)
        ],
    )

    assert unclaimed_occurrences(deps.content, deps.sentences, spans) == []


def test_swept_spans_are_reviewed_by_the_critic_and_substituted():
    """A repeat the annotator skipped reaches the Critic and the resolved text.

    The Critic is shown the swept Mention Span like any other, and accepting
    it puts the second ``he`` into the resolved text -- which is the whole
    point: an unresolved repeat is a pronoun the graph never sees.
    """

    content = "Newsom spoke. Then he paused and he sat down."
    annotator_agent = get_annotator_agent(defer_check=True)
    critic_agent = get_critic_agent(defer_check=True)
    reviewed: list[tuple[str, int]] = []

    def mock_annotator(messages, info):
        return mention_response(
            info,
            [
                {
                    "sentence_label": "2",
                    "mention_text": "he",
                    "canonical_entity_name": "Gavin Newsom",
                }
            ],
        )

    def mock_critic(messages, info):
        verdicts = [
            {
                "sentence_label": "2",
                "mention_text": "he",
                "occurrence": occurrence,
                "accepted": True,
            }
            for occurrence in (1, 2)
        ]
        reviewed.extend(("he", verdict["occurrence"]) for verdict in verdicts)
        return critic_response(info, verdicts)

    with (
        annotator_agent.override(model=FunctionModel(mock_annotator)),
        critic_agent.override(model=FunctionModel(mock_critic)),
    ):
        run = PydanticAICoreferenceAdapter(
            annotator_agent=annotator_agent,
            critic_agent=critic_agent,
        ).resolve(content)

    assert ("he", 2) in reviewed
    assert run.resolved_text == "Newsom spoke. Then Gavin Newsom paused and Gavin Newsom sat down."


def test_the_sweep_is_not_counted_as_a_retry():
    """Nothing was asked of a model, so no round was spent.

    Folding the sweep into ``retry_count`` would make every article with a
    repeated pronoun look like it had needed a correction round it never ran.
    """

    content = "Newsom spoke. Then he paused and he sat down."
    annotator_agent = get_annotator_agent(defer_check=True)
    critic_agent = get_critic_agent(defer_check=True)

    def mock_annotator(messages, info):
        return mention_response(
            info,
            [
                {
                    "sentence_label": "2",
                    "mention_text": "he",
                    "canonical_entity_name": "Gavin Newsom",
                }
            ],
        )

    def mock_critic(messages, info):
        return critic_response(
            info,
            [
                {
                    "sentence_label": "2",
                    "mention_text": "he",
                    "occurrence": occurrence,
                    "accepted": True,
                }
                for occurrence in (1, 2)
            ],
        )

    with (
        annotator_agent.override(model=FunctionModel(mock_annotator)),
        critic_agent.override(model=FunctionModel(mock_critic)),
    ):
        run = PydanticAICoreferenceAdapter(
            annotator_agent=annotator_agent,
            critic_agent=critic_agent,
        ).resolve(content)

    assert run.retry_count == 0


def test_the_annotator_is_told_to_number_repeats():
    """The prompt asks for what the sweep otherwise has to recover."""

    assert "every occurrence" in ANNOTATOR_INSTRUCTIONS
    assert "`He` and `he` are counted separately" in ANNOTATOR_INSTRUCTIONS
