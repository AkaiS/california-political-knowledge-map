"""The annotator-only run is the pipeline's first half and nothing else.

These tests exist because a baseline that drifts from the thing it is a
baseline for measures nothing. They pin the two properties that make the
comparison valid: the annotator is asked for the same thing, and its
answer passes the same deterministic validation.
"""

import pytest
from pydantic_ai.models.function import FunctionModel
from test_coreference import mention_response, rendered_request

from knowledge_map.adapters.coreference import (
    ANNOTATION_PROMPT,
    CoreferenceResolutionError,
    annotate_coreferences_run,
    get_annotator_agent,
)

ARTICLE = "Gavin Newsom signed a bill. He was happy. Katie Porter agreed."


def _annotator(spans, seen=None):
    """An annotator that answers with ``spans``, recording what it was shown."""

    def mock_annotator(messages, info):
        if seen is not None:
            seen.append(rendered_request(messages))
        return mention_response(info, spans)

    agent = get_annotator_agent(defer_check=True)
    return agent, FunctionModel(mock_annotator)


def _run(spans, seen=None):
    agent, model = _annotator(spans, seen)
    with agent.override(model=model):
        return annotate_coreferences_run(ARTICLE, annotator_agent=agent)


def test_the_annotator_is_asked_for_exactly_what_production_asks_for() -> None:
    """The same prompt constant, not a paraphrase of it."""

    seen: list[str] = []
    _run([{"sentence_label": "2", "mention_text": "He", "canonical_entity_name": "Gavin Newsom"}], seen)

    assert len(seen) == 1
    assert ANNOTATION_PROMPT in seen[0]
    assert "[1] Gavin Newsom signed a bill." in seen[0]


def test_a_located_span_survives_and_is_marked_validation_not_critic() -> None:
    """No Critic ran, so no outcome may claim a verdict one gave."""

    run = _run(
        [{"sentence_label": "2", "mention_text": "He", "canonical_entity_name": "Gavin Newsom"}]
    )

    assert [span.canonical_entity_name for span in run.surviving_spans] == ["Gavin Newsom"]
    assert [(o.stage, o.outcome) for o in run.outcomes] == [("validation", "accepted")]
    assert run.failure_type is None
    assert run.discarded_proportion == 0.0
    assert "Gavin Newsom was happy." in run.resolved_text


def test_the_critic_is_never_called() -> None:
    """The baseline is one model call; a second one would not be a baseline."""

    calls: list[str] = []

    def mock_annotator(messages, info):
        calls.append("annotator")
        return mention_response(
            info,
            [{"sentence_label": "2", "mention_text": "He", "canonical_entity_name": "Gavin Newsom"}],
        )

    agent = get_annotator_agent(defer_check=True)
    with agent.override(model=FunctionModel(mock_annotator)):
        annotate_coreferences_run(ARTICLE, annotator_agent=agent)

    assert calls == ["annotator"]


def test_the_same_deterministic_validation_still_discards() -> None:
    """An unlocatable span is dropped here exactly as the pipeline drops it."""

    run = _run(
        [
            {"sentence_label": "2", "mention_text": "He", "canonical_entity_name": "Gavin Newsom"},
            {"sentence_label": "2", "mention_text": "She", "canonical_entity_name": "Katie Porter"},
        ]
    )

    assert [span.mention_text for span in run.surviving_spans] == ["He"]
    assert run.discarded_proportion == pytest.approx(0.5)
    assert {o.outcome for o in run.outcomes} == {"accepted", "discarded"}


def test_an_annotator_returning_nothing_fails_the_way_production_fails() -> None:
    with pytest.raises(CoreferenceResolutionError) as caught:
        _run([])

    assert caught.value.failure_type == "no_mentions_returned"
    assert caught.value.resolution_run is not None


def test_an_annotator_whose_every_span_is_unlocatable_fails_as_discarded() -> None:
    """The output validator retries first, then the run fails as production does."""

    with pytest.raises(CoreferenceResolutionError) as caught:
        _run(
            [{"sentence_label": "2", "mention_text": "She", "canonical_entity_name": "Katie Porter"}]
        )

    assert caught.value.failure_type == "all_mentions_discarded"
    # What the annotator returned travels with the failure, because that is
    # what a prompt fix is made against.
    assert caught.value.resolution_run is not None
    assert caught.value.resolution_run.mention_spans
