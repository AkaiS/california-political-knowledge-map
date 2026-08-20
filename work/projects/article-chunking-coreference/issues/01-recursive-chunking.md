Labels: completed

## What to build

A text chunking utility in Python using the `chonkie` library. It should divide a resolved plain text article into contiguous segments (Article Chunks) using `chonkie.RecursiveChunker` to keep sentences and paragraphs intact, and `chonkie.OverlapRefinery` to add overlap.

The chunker utility must:
1. Configure `chonkie.RecursiveChunker` with `tokenizer="character"` and a maximum chunk size configured by the environment variable `CHUNK_SIZE` (defaulting to 1000).
2. Apply sliding overlap between consecutive chunks using `chonkie.OverlapRefinery` (with `tokenizer="character"`, `method="prefix"`, and `mode="token"`), where the overlap context size is configured by the environment variable `CHUNK_OVERLAP_PCT` (defaulting to 0.10, or 10% of the chunk size).

## Acceptance criteria

- [x] The utility correctly initializes `chonkie.RecursiveChunker` and `chonkie.OverlapRefinery` using the character tokenizer.
- [x] Chunks are recursively split at natural boundaries without the base chunk size exceeding `CHUNK_SIZE` characters.
- [x] Overlap between consecutive chunks is configured correctly via `OverlapRefinery` using `CHUNK_OVERLAP_PCT` as context size.
- [x] The utility reads chunk size and overlap settings from environment variables (`CHUNK_SIZE` and `CHUNK_OVERLAP_PCT`) with safe defaults (1000 size, 0.10 overlap).
- [x] Unit tests verify correctness on edge cases (e.g. extremely short texts, texts with no spaces, texts exactly matching chunk size).

## Blocked by

None - can start immediately

## Comments

### Previously discussed — 2026-08-19 grilling session

This issue is `completed`; the decisions below change `chunk_article` and need
their own issue. Recorded here because this issue owns the code.

Finding: `chunk_article` in
[utils/chunking.py](../../../../src/knowledge_map/utils/chunking.py) never passes
`merge` to `OverlapRefinery`, so it takes the default `merge=True`. Verified
empirically on a 2,057-character article at `chunk_size=300`:

- `start_index`/`end_index` tile the article exactly once — spans sum to 2,057.
- `text` does **not** equal `article[start_index:end_index]`. The refinery
  prepends the previous chunk's tail at
  [overlap.py:313](../../../../.venv/lib/python3.13/site-packages/chonkie/refinery/overlap.py:313),
  under `if self.merge`. `setattr(chunk, "context", context)` runs regardless.
- With `merge=False`, `text == article[start_index:end_index]` holds exactly and
  `context` still carries the prefix separately.

Decisions:

- **Pass `merge=False`.** Offsets and `text` then agree by construction, which is
  what lets the numbered sentence table align to chunk boundaries — each sentence
  falls in exactly one `[start_index, end_index)` range.
- **Each consumer gets a different string.** Entity Extraction gets `text` alone —
  Coreference Resolution is what supplies antecedents, so the overlap prefix is
  redundant there. Embedding gets `context + text`. Reader display gets `text`
  alone, since `context` is a duplicate of the previous chunk.
