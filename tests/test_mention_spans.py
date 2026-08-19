import pytest
from pydantic import ValidationError

from knowledge_map.adapters.coreference import (
    LocatedMentionSpan,
    substitute_mention_spans,
    validate_mention_spans,
)
from knowledge_map.schemas import MentionSpan
from knowledge_map.utils.sentences import NumberedSentence


def numbered_sentence(content: str, label: str = "1") -> NumberedSentence:
    return NumberedSentence(
        label=label,
        text=content,
        start_index=0,
        end_index=len(content),
    )


def test_mention_span_has_model_fields_only_and_defaults_to_first_occurrence():
    mention = MentionSpan(
        sentence_label="1",
        mention_text="her",
        canonical_entity_name="Gavin Newsom",
    )

    assert mention.occurrence == 1
    assert set(MentionSpan.model_fields) == {
        "sentence_label",
        "mention_text",
        "occurrence",
        "canonical_entity_name",
    }
    assert mention.model_dump() == {
        "sentence_label": "1",
        "mention_text": "her",
        "occurrence": 1,
        "canonical_entity_name": "Gavin Newsom",
    }


def test_occurrence_must_be_one_based():
    with pytest.raises(ValidationError):
        MentionSpan(
            sentence_label="1",
            mention_text="her",
            occurrence=0,
            canonical_entity_name="Gavin Newsom",
        )


def test_validation_derives_a_range_from_the_sentence_and_not_the_model():
    content = "There she spoke."
    mention = MentionSpan(
        sentence_label="1",
        mention_text="she",
        canonical_entity_name="Gavin Newsom",
    )

    result = validate_mention_spans(content, [numbered_sentence(content)], [mention])

    assert result.discards == []
    assert result.valid_spans == [
        LocatedMentionSpan(
            mention_span=mention,
            start_index=6,
            end_index=9,
        )
    ]


def test_validation_offsets_a_match_by_the_named_sentence_start():
    content = "Prefix. She spoke."
    sentence = NumberedSentence(
        label="2",
        text="She spoke.",
        start_index=8,
        end_index=len(content),
    )
    mention = MentionSpan(
        sentence_label="2",
        mention_text="She",
        canonical_entity_name="Gavin Newsom",
    )

    result = validate_mention_spans(content, [sentence], [mention])

    assert result.valid_spans[0].start_index == 8
    assert result.valid_spans[0].end_index == 11


def test_word_boundary_matching_does_not_find_her_inside_there():
    content = "there"
    mention = MentionSpan(
        sentence_label="1",
        mention_text="her",
        canonical_entity_name="Gavin Newsom",
    )

    result = validate_mention_spans(content, [numbered_sentence(content)], [mention])

    assert result.valid_spans == []
    assert result.discards[0].mention_span == mention
    assert "does not occur" in result.discards[0].reason


def test_unknown_sentence_label_is_discarded_without_raising():
    mention = MentionSpan(
        sentence_label="99",
        mention_text="her",
        canonical_entity_name="Gavin Newsom",
    )

    result = validate_mention_spans(
        "She spoke.",
        [numbered_sentence("She spoke.")],
        [mention],
    )

    assert result.valid_spans == []
    assert result.discards[0].mention_span == mention
    assert "unknown sentence label" in result.discards[0].reason


def test_missing_mention_text_and_excess_occurrence_are_discarded():
    content = "She spoke."
    missing = MentionSpan(
        sentence_label="1",
        mention_text="her",
        canonical_entity_name="Gavin Newsom",
    )
    too_late = MentionSpan(
        sentence_label="1",
        mention_text="She",
        occurrence=2,
        canonical_entity_name="Gavin Newsom",
    )

    result = validate_mention_spans(
        content,
        [numbered_sentence(content)],
        [missing, too_late],
    )

    assert [discard.mention_span for discard in result.discards] == [missing, too_late]
    assert "does not occur" in result.discards[0].reason
    assert "exceeds" in result.discards[1].reason


def test_occurrences_resolve_repeated_mentions_independently():
    content = "She thanked her and her."
    first = MentionSpan(
        sentence_label="1",
        mention_text="her",
        occurrence=1,
        canonical_entity_name="Gavin Newsom",
    )
    second = first.model_copy(
        update={"occurrence": 2, "canonical_entity_name": "The committee"}
    )

    result = substitute_mention_spans(
        content,
        [numbered_sentence(content)],
        [first, second],
    )

    assert result.resolved_text == "She thanked Gavin Newsom and The committee."
    assert result.discards == []


def test_overlapping_ranges_keep_the_first_and_report_the_dropped_span():
    content = "She spoke."
    first = MentionSpan(
        sentence_label="1",
        mention_text="She",
        canonical_entity_name="Gavin Newsom",
    )
    overlapping = MentionSpan(
        sentence_label="1",
        mention_text="She",
        canonical_entity_name="A different entity",
    )

    result = substitute_mention_spans(
        content,
        [numbered_sentence(content)],
        [first, overlapping],
    )

    assert result.resolved_text == "Gavin Newsom spoke."
    assert len(result.discards) == 1
    assert result.discards[0].mention_span == overlapping
    assert "overlaps" in result.discards[0].reason


def test_empty_and_boundary_adjacent_substitutions_are_lossless_elsewhere():
    content = "()"
    left = MentionSpan(
        sentence_label="1",
        mention_text="(",
        canonical_entity_name="left",
    )
    right = MentionSpan(
        sentence_label="1",
        mention_text=")",
        canonical_entity_name="right",
    )
    sentences = [numbered_sentence(content)]

    empty = substitute_mention_spans(content, sentences, [])
    result = substitute_mention_spans(content, sentences, [left, right])

    assert empty.resolved_text == content
    assert empty.discards == []
    assert result.resolved_text == "leftright"
    assert result.discards == []
