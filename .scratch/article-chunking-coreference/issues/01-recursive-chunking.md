Status: ready-for-agent

## What to build

A text chunking utility in Python using the `chonkie` library. It should divide a resolved plain text article into contiguous segments (Article Chunks) using `chonkie.RecursiveChunker` to keep sentences and paragraphs intact, and `chonkie.OverlapRefinery` to add overlap.

The chunker utility must:
1. Configure `chonkie.RecursiveChunker` with `tokenizer="character"` and a maximum chunk size configured by the environment variable `CHUNK_SIZE` (defaulting to 1000).
2. Apply sliding overlap between consecutive chunks using `chonkie.OverlapRefinery` (with `tokenizer="character"`, `method="prefix"`, and `mode="token"`), where the overlap context size is configured by the environment variable `CHUNK_OVERLAP_PCT` (defaulting to 0.10, or 10% of the chunk size).

## Acceptance criteria

- [ ] The utility correctly initializes `chonkie.RecursiveChunker` and `chonkie.OverlapRefinery` using the character tokenizer.
- [ ] Chunks are recursively split at natural boundaries without the base chunk size exceeding `CHUNK_SIZE` characters.
- [ ] Overlap between consecutive chunks is configured correctly via `OverlapRefinery` using `CHUNK_OVERLAP_PCT` as context size.
- [ ] The utility reads chunk size and overlap settings from environment variables (`CHUNK_SIZE` and `CHUNK_OVERLAP_PCT`) with safe defaults (1000 size, 0.10 overlap).
- [ ] Unit tests verify correctness on edge cases (e.g. extremely short texts, texts with no spaces, texts exactly matching chunk size).

## Blocked by

None - can start immediately
