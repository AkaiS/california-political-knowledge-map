"""Split Source Article content into addressable, numbered sentences."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise

from chonkie import SentenceChunker

DEFAULT_MIN_SENTENCE_CHARACTERS = 12


class SentenceRangeInvariantError(ValueError):
    """A sentence table failed the positional invariant it must uphold.

    Raised, not asserted, so the checks survive ``python -O``; a broken
    invariant silently corrupts Mention Span substitution.
    """


@dataclass(frozen=True, slots=True)
class NumberedSentence:
    """A contiguous sentence range in Source Article content.

    Labels are one-based strings, copied verbatim by the annotator.
    ``end_index`` is exclusive, for ordinary Python slicing.
    """

    label: str
    text: str
    start_index: int
    end_index: int


def split_into_numbered_sentences(
    content: str,
    *,
    min_characters_per_sentence: int = DEFAULT_MIN_SENTENCE_CHARACTERS,
) -> list[NumberedSentence]:
    """Return ``content`` as an ordered list of contiguous sentence ranges.

    Fragments below ``min_characters_per_sentence`` fold into the preceding
    sentence, or into the following one at the start of content.  No character
    is ever dropped, so the ranges tile ``content`` exactly.
    """

    if min_characters_per_sentence < 1:
        raise ValueError("min_characters_per_sentence must be at least 1")

    if not content:
        return []

    # A one-character chunk limit makes each chunk one raw sentence.
    raw_chunks = SentenceChunker(
        tokenizer="character",
        chunk_size=1,
        min_characters_per_sentence=1,
    ).chunk(content)

    # Chonkie returns no chunks for whitespace-only input; it is still one
    # range here, or the exact-content invariant would not hold.
    if not raw_chunks:
        raw_ranges = [(0, len(content))]
    else:
        raw_ranges = [(chunk.start_index, chunk.end_index) for chunk in raw_chunks]

        if "".join(content[start:end] for start, end in raw_ranges) != content:
            raise SentenceRangeInvariantError(
                "raw sentence ranges must concatenate back to the exact content"
            )
        if not all(
            chunk.text == content[chunk.start_index : chunk.end_index]
            for chunk in raw_chunks
        ):
            raise SentenceRangeInvariantError(
                "each raw sentence's text must equal the content at its range"
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

    # These are deliberate runtime checks: the sentence table is the positional
    # source of truth for later Mention Span substitution.
    if sentences[0].start_index != 0:
        raise SentenceRangeInvariantError(
            "the first sentence must start at the beginning of the content"
        )
    if sentences[-1].end_index != len(content):
        raise SentenceRangeInvariantError(
            "the last sentence must end at the end of the content"
        )
    if not all(
        sentence.start_index == previous.end_index
        for previous, sentence in pairwise(sentences)
    ):
        raise SentenceRangeInvariantError(
            "sentence ranges must be contiguous with no gap or overlap"
        )
    if not all(
        sentence.text == content[sentence.start_index : sentence.end_index]
        for sentence in sentences
    ):
        raise SentenceRangeInvariantError(
            "each sentence's text must equal the content at its range"
        )
    if "".join(sentence.text for sentence in sentences) != content:
        raise SentenceRangeInvariantError(
            "sentence texts must concatenate back to the exact content"
        )

    return sentences
