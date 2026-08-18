"""Split Source Article content into addressable, numbered sentences."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise

from chonkie import SentenceChunker

DEFAULT_MIN_SENTENCE_CHARACTERS = 12


@dataclass(frozen=True, slots=True)
class NumberedSentence:
    """A contiguous sentence range in Source Article content.

    Labels are one-based strings because they are copied by the annotator into
    a structured response.  ``end_index`` is exclusive, matching Chonkie's
    range convention and normal Python slicing.
    """

    label: str
    text: str
    start_index: int
    end_index: int

    @property
    def start(self) -> int:
        """Return the sentence's inclusive start position."""

        return self.start_index

    @property
    def end(self) -> int:
        """Return the sentence's exclusive end position."""

        return self.end_index


def split_into_numbered_sentences(
    content: str,
    *,
    min_characters_per_sentence: int = DEFAULT_MIN_SENTENCE_CHARACTERS,
) -> list[NumberedSentence]:
    """Return ``content`` as an ordered list of contiguous sentence ranges.

    Chonkie's sentence splitter supplies the raw, exact ranges.  A raw
    fragment that is whitespace-only or shorter than the configured minimum is
    folded into the preceding sentence.  At the beginning of content, where a
    preceding sentence does not exist, such fragments are carried forward and
    become the prefix of the first sentence.  This keeps the output addressable
    without ever dropping a character.
    """

    if min_characters_per_sentence < 1:
        raise ValueError("min_characters_per_sentence must be at least 1")

    if not content:
        return []

    # A one-character chunk limit makes each returned Chonkie chunk one raw
    # sentence while retaining Chonkie's sentence-boundary and range logic.
    raw_chunks = SentenceChunker(
        tokenizer="character",
        chunk_size=1,
        min_characters_per_sentence=1,
    ).chunk(content)

    # Chonkie intentionally returns no chunks for whitespace-only input.  It
    # is still one contiguous range from this utility's perspective: otherwise
    # the exact-content invariant could not hold.
    if not raw_chunks:
        raw_ranges = [(0, len(content))]
    else:
        raw_ranges = [(chunk.start_index, chunk.end_index) for chunk in raw_chunks]

        assert "".join(
            content[start:end] for start, end in raw_ranges
        ) == content
        assert all(
            chunk.text == content[chunk.start_index : chunk.end_index]
            for chunk in raw_chunks
        )

    merged_ranges: list[tuple[int, int]] = []
    leading_fold_start: int | None = None

    for start, end in raw_ranges:
        fragment = content[start:end]
        should_fold = not fragment.strip() or len(fragment) < min_characters_per_sentence

        if not merged_ranges:
            if should_fold:
                if leading_fold_start is None:
                    leading_fold_start = start
                continue

            merged_ranges.append(
                (leading_fold_start if leading_fold_start is not None else start, end)
            )
            leading_fold_start = None
            continue

        if should_fold:
            previous_start, _ = merged_ranges[-1]
            merged_ranges[-1] = (previous_start, end)
        else:
            merged_ranges.append((start, end))

    if not merged_ranges:
        # All fragments were foldable, so keep them as one range rather than
        # returning a lossy empty result.
        merged_ranges.append((0, len(content)))

    sentences = [
        NumberedSentence(
            label=str(index),
            text=content[start:end],
            start_index=start,
            end_index=end,
        )
        for index, (start, end) in enumerate(merged_ranges, start=1)
    ]

    # These are deliberate runtime assertions: the sentence table is the
    # positional source of truth for later Mention Span substitution.
    assert sentences[0].start_index == 0
    assert sentences[-1].end_index == len(content)
    assert all(
        sentence.start_index == previous.end_index
        for previous, sentence in pairwise(sentences)
    )
    assert all(
        sentence.text == content[sentence.start_index : sentence.end_index]
        for sentence in sentences
    )
    assert "".join(sentence.text for sentence in sentences) == content

    return sentences


# Keep the shorter name available for callers that describe the operation as
# "numbering" rather than "splitting".
split_numbered_sentences = split_into_numbered_sentences
