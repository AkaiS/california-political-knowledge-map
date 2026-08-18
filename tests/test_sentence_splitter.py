from itertools import pairwise

from knowledge_map.utils.sentences import (
    NumberedSentence,
    split_into_numbered_sentences,
)


def test_empty_content_returns_no_sentences():
    assert split_into_numbered_sentences("") == []


def test_content_without_delimiters_is_one_exact_sentence():
    content = "A Source Article without a sentence delimiter"

    sentences = split_into_numbered_sentences(content)

    assert sentences == [
        NumberedSentence(
            label="1",
            text=content,
            start_index=0,
            end_index=len(content),
        )
    ]


def test_configured_minimum_controls_short_fragment_folding():
    content = "One. Two."

    sentences = split_into_numbered_sentences(
        content,
        min_characters_per_sentence=1,
    )

    assert [sentence.text for sentence in sentences] == ["One. ", "Two."]


def test_sentence_ranges_and_labels_are_contiguous():
    content = "The first sentence is long enough. The second sentence is long enough."

    sentences = split_into_numbered_sentences(content)

    assert [sentence.label for sentence in sentences] == ["1", "2"]
    assert [sentence.text for sentence in sentences] == [
        "The first sentence is long enough. ",
        "The second sentence is long enough.",
    ]
    assert sentences[0].start_index == 0
    assert sentences[-1].end_index == len(content)
    assert all(
        sentence.text == content[sentence.start_index : sentence.end_index]
        for sentence in sentences
    )
    assert all(
        previous.end_index == sentence.start_index
        for previous, sentence in pairwise(sentences)
    )


def test_short_and_whitespace_fragments_fold_into_preceding_sentence():
    content = "This is a sufficiently long sentence.\n\nTiny. This is another sufficiently long sentence."

    sentences = split_into_numbered_sentences(content)

    assert [sentence.text for sentence in sentences] == [
        "This is a sufficiently long sentence.\n\nTiny. ",
        "This is another sufficiently long sentence.",
    ]
    assert "\n\n" in sentences[0].text
    assert not any(not sentence.text.strip() for sentence in sentences)


def test_invariant_holds_for_newlines_quotes_parentheses_and_abbreviation():
    content = (
        'Sen. Rivera said, "The proposal passed (despite objections)."\n'
        "The committee will meet again.\n\n"
        "Members expect a vote."
    )

    sentences = split_into_numbered_sentences(content)

    assert "".join(sentence.text for sentence in sentences) == content
    assert sentences[0].start_index == 0
    assert sentences[-1].end_index == len(content)
    assert all(
        sentence.text == content[sentence.start_index : sentence.end_index]
        for sentence in sentences
    )


def test_whitespace_only_content_remains_lossless():
    content = " \n\n"

    sentences = split_into_numbered_sentences(content)

    assert len(sentences) == 1
    assert sentences[0].text == content
    assert sentences[0].start_index == 0
    assert sentences[0].end_index == len(content)
