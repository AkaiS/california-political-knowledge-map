Status: ready-for-agent

## What to build

A recursive text splitter utility in Python. It should divide a resolved plain text article into contiguous segments (Article Chunks) using natural delimiters (e.g. `\n\n`, `\n`, ` `, ``) so that sentences and paragraphs remain intact as much as possible.

The splitter must:
1. Limit chunks to a maximum character size configured by the environment variable `CHUNK_SIZE` (defaulting to 1000).
2. Create a sliding overlap between consecutive chunks based on the environment variable `CHUNK_OVERLAP_PCT` (defaulting to 0.10, or 10%).

## Acceptance criteria

- [ ] The splitter function recursively splits text at natural boundaries without exceeding `CHUNK_SIZE` characters.
- [ ] Each consecutive chunk has an overlap equal to `CHUNK_SIZE * CHUNK_OVERLAP_PCT` characters with the previous chunk.
- [ ] Splitter reads settings from environment variables with safe defaults (1000 size, 10% overlap).
- [ ] High-coverage unit tests verify correctness on edge cases (e.g. extremely short texts, texts with no spaces, texts exactly matching chunk size).

## Blocked by

None - can start immediately
