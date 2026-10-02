# Review selected evidence and generation

RAG review judges the evidence selected for the Chat Agent and its final
generation. It does not grade question preparation, structural construction,
branch execution or the whole Chat Session. Those remain available in the
separate end-to-end chat reviewer.

Start the same review server in RAG mode:

```sh
uv run python scripts/review_chat_eval.py --mode rag
```

Open `http://127.0.0.1:8765/`. The run list includes retrieval and chat reports.
Use `--reports-dir evals/reports/retrieval` to show only retrieval reports,
or `--port 8766` when another reviewer is already running.

A retrieval report supplies selected context and retrieval reference metrics.
It has no final generation, so answer relevance and faithfulness are unavailable.
A chat report supplies the context and final generation from its own execution.
Existing unlabeled chat runs have no reference retrieval scores. The reviewer
never joins context from one run to an answer from another, or treats an absent
measurement as zero.

## Judgment inputs

Each case shows the approved retrieval question, scope, selected passage wording
and citations, and the final rendered generation when present. It does not serve
rewrites, assessments, branch candidates, model messages or application spans
through the focused report API. The run specifications and metric dashboard are
visible immediately above these inputs.

Record three independent binary judgments, with Uncertain available when the
inputs do not let you decide:

| Judgment | Pass criterion |
| --- | --- |
| Context relevance | Selected passages address the question's subjects, session and relationship without substantial off-topic material. |
| Answer relevance | The generation addresses the approved question's requested focus. |
| Answer faithfulness | Factual claims and citations have support in the selected passages, without invention or misinterpretation. |

Each axis has a short judgment-evidence field. Quote the passage or answer claim
that explains the decision. There is no whole-case verdict, general critique,
or separate omission label. Reference recall measures coverage separately.
Missing context or generation disables the affected judgments. Cases with no
judgment inputs appear as unjudgeable and do not enter review progress.

The diagnosis panel derives a constrained interpretation from these labels.
Low context relevance points to evidence selection; relevant context with
unfaithful generation points to unsupported claims or misinterpretation;
faithful but irrelevant generation points to answer focus. It is a review aid,
not a root-cause claim or an automatic quality judge.

## Retrieval measurements

Choose full-text, dense, structural or fusion to see run means and case scores.
The dashboard includes Recall@1/5/10/50, reciprocal rank within 50 chunks, and
final-context recall and complete evidence. The mean reciprocal rank is shown
at run level; a single case shows reciprocal rank. Hover a run value for its
scored population. Skipped structural branches are not counted as zero.

Two-hop Recall@k is calculated when the reference defines two evidence groups
per answer and the report has replayable ranks. It measures the fraction of
reference answers with a witness for both groups, including alternative witnesses
and a chunk that supports both hops. The dashboard states that unit explicitly.
General complete-evidence coverage is not relabeled as two-hop recall when the
reference has a different shape.

Precision@k and NDCG@k are visible, with their requirements in the metric
specifications. Current silver references list positive witnesses rather than
exhaustive relevance judgments or relevance grades. These metrics therefore
show Unavailable. An unlisted passage cannot be assumed irrelevant. A run that
records those metrics can display them directly; the reviewer does not invent
negative labels or grades.

Specs include dataset, label quality, split, revision, metric version, chunk
budget, RRF weights and candidate limits, and Evidence Assembly limits when
recorded. Article coverage applies the chunk budget before deduplicating Source
Article identities. The initial 25 cases are silver training examples, not a
held-out estimate of answer accuracy.

## Saving and navigation

RAG labels save beside each report as `<report>.rag-reviews.json`, independently
of the end-to-end `<report>.reviews.json`. Both may be committed with the report.
The updated shared editor supplies autosave, report-bound browser drafts, recovery,
undo and save-before-navigation. Changed reports reject stale writes.

Choose an axis, then use `1` for Pass, `2` for Fail or `D` for Uncertain. `U`
undoes the last label or note edit. Arrow keys navigate; Cmd/Ctrl+S saves;
Cmd/Ctrl+Enter saves and advances. These annotation shortcuts leave text editing
alone. A clear action clears one axis while retaining its evidence note.

Deterministic checks:

```sh
uv run pytest tests/test_rag_review.py tests/test_chat_eval_review.py
uv run node --test tests/chat_eval_review_editing.test.mjs tests/rag_eval_review.test.mjs
```
