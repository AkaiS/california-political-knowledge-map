# Review sampled Article Chunks

The chunk view presents one approved question and one Article Chunk. Label
its relevance High, Low or Defer, with an optional description. It has no
generation, retrieval scores, ranks or provisional reference labels. These
judgments belong to a query–chunk pair; the same chunk can receive different
labels for different questions.

Open **Chunk review** from the RAG reviewer, or visit
`http://127.0.0.1:8765/chunks`. The existing server serves both views:

```sh
uv run python scripts/review_chat_eval.py --mode rag
```

Choices autosave and advance. Descriptions autosave after typing pauses.
Previous, Next, an item-number jump, unmarked/deferred filters and Undo allow
revisiting judgments. Shortcuts are 1 High, 2 Low, D Defer, U Undo and arrow
keys. Shortcuts do not grade a chunk while typing a description.

High means the chunk supplies useful evidence for the requested question or
one of its required steps. Mentioning a named subject alone does not establish
relevance. Low means it does not help answer the question. Defer retains an
uncertain judgment for another look; it never becomes an implicit Low.

## Freeze a sample

Sampling runs in a separate script. It replays the recorded production fusion,
uses the top ten unique chunks per attempted retrieval, allocates the requested
sample evenly across nonempty attempts, samples randomly within each attempt
and shuffles presentation order. Empty attempts remain recorded in the sampling
manifest. Sampling never filters on provisional relevance or answer success.

```sh
uv run python scripts/build_chunk_review_sample.py \
  --report evals/reports/retrieval/20261002T233848Z-e237389-local-gemma4-26b-1499ceec2201.json \
  --size 200 --seed 42 \
  --output evals/chunk-samples/retrieval-20261002-top10-200-seed42.json
```

For 25 attempts, 200 items selects eight of each attempt's top ten; 100 selects
four. Repeat `--report` to sample multiple compact retrieval runs. The sampler
rejects a repeated report and refuses to overwrite a sample. A different size
or seed should use a new filename.

The prepared 200-item sample contains 167 texts from the October 2 report and
33 texts loaded from the current graph on October 6. Original ranks are those
of the recorded run. Graph-loaded text is a later snapshot, not a claim about
historical wording. The sample freezes text, its hash, observation time and
origin, source report hashes, chunk and Source Article IDs, ranks and seed.
Missing graph text aborts creation rather than biasing the sample by dropping
that result. The source report and RAG annotations remain unchanged.

## Use human labels to calibrate a judge

Labels save beside the sample in `.chunk-reviews.json`. **Export High / Low
labels** downloads JSONL with the question, full chunk, human label,
description and provenance. Unmarked and deferred items are excluded. No
LLM judge runs while collecting these labels.

The export includes a question-group hash. Keep every chunk for one question
together when making training, development and held-out judge-validation
splits. Randomly splitting individual chunks from the same question would
leak familiar questions across those splits. The 200 pairs cover 25 questions;
they are a calibration starting point. Check performance on both High and Low
labels and untouched questions before trusting the judge. See
[the RAG relevance research](rag-relevance-research.md).

This sampled dataset does not replace the run's reference metrics or produce
exact Precision@10, recall or NDCG. Those require their respective ranking
coverage and relevance references. It supplies human examples for the separate
chunk-relevance judge.
