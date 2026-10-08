# Review selected evidence and generation

For a separate question-and-chunk annotation workflow, use
[sampled chunk review](chunk-review.md). It collects High / Low / Defer labels
from a sample of each retrieval attempt's fused top ten.

RAG review judges the evidence selected for the Chat Agent and its final
generation. It does not grade question preparation, structural construction,
branch execution or the whole Chat Session. Those remain available in the
separate end-to-end chat reviewer.

## Start the reviewer

From a prepared checkout, run:

```sh
./scripts/start-rag-reviewer.sh
```

Open the ready URL printed by the launcher. The run list includes retrieval and
chat reports, and **Chunk review** opens the sampled chunk view. The launcher
prints the resolved checkout and data directories. It reuses a ready server only
when its mode, checkout, report directory and sample directory match. Otherwise
the operating system assigns a free loopback port. Other reviewers keep running.

The server runs detached after the command exits. Logs and reuse records live
under `.scratch/rag-reviewer/`. A reused server without a recorded log file prints
`Log: unavailable for reused server`. Startup waits at most 30 seconds for readiness,
including the launch lock and identity probes. If a started server fails, the
launcher prints its log path and stops only the process started by that attempt.
Concurrent launches for the same directories share one server. Repeating the
command prints the same ready URL while that server is running, which preserves
the address used by browser-local review drafts.

Use `--reports-dir evals/reports/retrieval` to show only retrieval reports,
`--samples-dir <path>` to select another sample directory, or `--timeout <seconds>`
to change the readiness deadline. Relative paths resolve from the checkout root.
To stop a server you started, read its PID at `<ready-url>api/identity` and send
that PID `SIGTERM`. Saved annotations remain beside their reports and samples.

The launcher uses `uv run --no-sync python -u` and does not install dependencies.
If the checkout has no prepared `.venv`, run `uv sync --locked --dev` first.
In a restricted sandbox, allow access to uv's runtime/cache and local loopback
sockets, including a detached subprocess. A denied launch cannot produce a ready
URL; inspect its error or the printed log before retrying.

## Choose a run

A new retrieval report supplies selected context, retrieval reference metrics
and the final Chat Agent answer from the same execution. Older retrieval-only
reports have no generation and must be rerun to judge answer relevance and
faithfulness. A chat report supplies context and final generation from its own execution.
Existing unlabeled chat runs have no reference retrieval scores. The reviewer
never joins context from one run to an answer from another, or treats an absent
measurement as zero.

## Judgment inputs

Each case shows the approved retrieval question, scope, selected passage wording
and citations, the selected graph facts supplied to generation, and the final
rendered generation when present. Graph facts are included only when all of their
evidence chunks reached the selected context, matching the production handoff.
It does not serve rewrites, assessments, branch candidates, model messages or application spans
through the focused report API. The run specifications and metric dashboard are
visible immediately above these inputs in an initially expanded, collapsible
panel. The case list scrolls independently of the evidence and answer.

Record three independent binary judgments as High or Low. Each has a description;
no category depends on a judgment in another category. Leave a selection blank
when the inputs do not let you decide:

| Judgment | High criterion |
| --- | --- |
| Context relevance | Selected passages address the question's subjects, session and relationship without substantial off-topic material. |
| Answer relevance | The generation addresses the approved question's requested focus. |
| Answer faithfulness | Factual claims and citations have support in the selected passages, without invention or misinterpretation. |

Each category has a short Description field. Quote the passage or answer claim
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

Reference precision@k counts reference-matching chunk slots among the first k
unique chunks, divided by k. Missing slots count as zero. For article-grain
references, each chunk from a listed Source Article counts. Like recall, this
measures agreement with provisional silver references; other useful passages
may be absent from those labels. It is distinct from human judgments of chunk
relevance. Existing bounded reports can compute it from retained ranks without
rerunning retrieval or rewriting the saved report. New runs record it directly.

NDCG@k remains unavailable when relevance grades are absent. Runs without either
reference labels and replayable ranks or a recorded precision score also leave
precision unavailable. An unavailable metric is not zero.

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

Choose a category, then use `1` for High or `2` for Low. `U`
undoes the last label or note edit. Arrow keys navigate; Cmd/Ctrl+S saves;
Cmd/Ctrl+Enter saves and advances. These annotation shortcuts leave text editing
alone. A clear action clears one category while retaining its description.
Stored High and Low labels use `pass` and `fail` respectively for compatibility
with existing reviews. Older `defer` labels remain readable but count as
incomplete until replaced with a binary judgment.

Deterministic checks:

```sh
uv run pytest tests/test_rag_review.py tests/test_chat_eval_review.py
uv run node --test tests/chat_eval_review_editing.test.mjs tests/rag_eval_review.test.mjs
```
