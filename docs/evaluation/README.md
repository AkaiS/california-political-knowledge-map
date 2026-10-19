# Evaluation guides

Choose the guide for the task at hand. Each review guide owns its commands and
annotation rules.

| Task | Guide |
| --- | --- |
| Start the RAG reviewer and judge selected evidence or final generation | [RAG review](rag-review.md) |
| Freeze a sample and label question–Article Chunk relevance | [Chunk review](chunk-review.md) |
| Run and review a whole Chat Session | [Chat answer review](chat-answer-review.md) |
| Collect observed Chat Session failures | [Chat error discovery](chat-error-discovery.md) |
| Understand retrieval references, metrics and measurement limits | [Retrieval evaluation](retrieval.md) |
| Understand RAG relevance judgments and judge calibration | [RAG relevance research](rag-relevance-research.md) |
| Annotate Coreference Resolution | [Coreference annotation](coreference-annotation.md) |
| Annotate Entity Extraction | [Extraction annotation](extraction-annotation.md) |
| Annotate Policy Area Classification | [Policy area annotation](policy-area-classification-annotation.md) |
| Annotate Topic Assignment | [Topic assignment annotation](topic-assignment-annotation.md) |

For evaluation artifact provenance and storage decisions, see
[ADR 0024](../adr/0024-evaluations-preserve-the-selected-population-and-progress.md).
Every completed Evaluation Run records its task's Headline Metrics in its
report, as [ADR 0026](../adr/0026-evaluation-reports-freeze-their-run-result.md)
decides. `uv run scripts/run_evaluation.py --report PATH --format markdown`
renders them as a scorecard, compared against the newest earlier Comparable
Run. To inspect
application decisions and model activity, use the
[Chat Session trail guide](../chat-session-trails.md).
