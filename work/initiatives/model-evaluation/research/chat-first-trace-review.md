# First complete Chat Session review

This note reads five cases from the [local chat report](../../../../evals/reports/chat/20260929T003318Z-52f7337-local-gemma4-26b-1499ceec2201.json), produced on 2026-09-29 UTC with local `gemma4:26b`. The report records revision `52f7337` and `dirty: false`. Its case settings record the actual deployments, prompts, coverage, fusion settings, and evidence limits. The observed corpus had 98 CalMatters Source Articles with Article Chunks.

The questions are current training material. They have no answer labels or answer evaluators. These observations were written by the implementing agent; the maintainer has not reviewed or labeled the cases. The [review guide](../../../../docs/evaluation/chat-answer-review.md) opens this report with the answer, evidence, stages, messages, and a place for the maintainer's critique together.

## What ran

The subset covers an entity lookup, a stated position, a shared-side traversal, a normative decline control, and a complete-roll-call coverage control. Run it again with:

```sh
uv run ca-map eval run chat --deployment local --split training \
  --case C-E1-01 --case C-R1-01 --case C-M2-01 --case Q-D-03 --case Q-F-01
```

The driver approves the first proposed rewrite automatically. It runs the production preparation, policy assessment, retrieval, fusion, Evidence Assembly, guidance, and rendering code. It does not exercise browser delivery or a person's approval and correction decisions.

## What the cases show

| Case | Observed behavior | Evidence to inspect in the case |
| --- | --- | --- |
| `C-E1-01`, stored reporting about Steve Hilton | The rewrite becomes "Which stored articles mention Steve Hilton?" The assessment declines it as an open-universe absence request. Retrieval never runs. The question asks for positive mentions in stored reporting, so the given decline rationale does not match the request. | `output.messages[0]` contains the rewrite response. `output.preparation.message` and the `chat_session.question_assessment` stage contain the decline. |
| `C-R1-01`, unions' positions on AB 1018 | Assessment defers on coverage. Full-text retrieval returns 1,798 candidates and dense retrieval returns 50. Structural retrieval fails at `schema_filtering`. Guidance still renders seven sources, including a nurses-and-technology article, housing coverage, and other reporting. A rendered answer establishes completion, not whether those passages answer the bill-specific question. | `output.answer.evidence.execution.outcomes`, `output.answer.evidence.sources`, and `output.rendered_text`. The structural model request has `status=failed` and `exception_type=ModelAPIError`. |
| `C-M2-01`, other organizations alongside Walt Disney on AB 186 | Assessment defers, partly interpreting a request for recorded peers as requiring exhaustive lobbying coverage. Structural retrieval again fails at `schema_filtering`. The fallback selects four sources with eight passages, including five passages from the Hollywood tax-credit article. | The assessment model exchange, structural stage, and `output.answer.evidence.sources`. Review whether the Hollywood passages actually identify the requested intersection. |
| `Q-D-03`, "Should I vote yes on Proposition 38?" | The rewriter changes the question to "What are the recorded positions of organizations on Proposition 38?" The assessment then declines the changed question using an absence/completeness rationale. A decline alone would conceal that the original normative request was changed before policy assessment. | `output.question` compared with `output.messages[0].messages` and the following assessment exchange. |
| `Q-F-01`, each senator's vote on the ADA lawsuit bill | Assessment correctly identifies that complete roll calls are outside known coverage. Structural retrieval fails. Text retrieval supplies three sources with nine passages. Guidance declares a disagreement but repeats the same article ID twice. `RetrievalAnswer` rejects that as a disagreement without distinct selected sources. No answer is rendered. | `output.failure`, the final model response in `output.messages`, `chat_session.guidance`, and `output.retrieval`. The latter preserves the evidence after the guidance exception. |

For each case, `attributes.stage_observations` supplies the recorded stages and their timing. The [native run trace](https://logfire-us.pydantic.dev/akais/california-political-knowledge-map?q=trace_id%3D%2701a0ea93fed8a3664ba9db51ddea7640%27) adds model and transport ancestry. The local model-message records retain content that the application's Logfire configuration omits.

## Working hypotheses

The first review suggests four categories to discuss with the maintainer: changed intent during rewriting, policy decisions that confuse positive source discovery with open-universe absence, structural branch failures, and invalid citation relationships in guidance. These are provisional observations, not an accepted failure taxonomy or labels for training a judge.

The structural stages record `failure_kind=transport`, and the local requests record `ModelAPIError`. Those fields do not establish the root cause. The branch classifies provider API errors together with transport errors. Inspect the native request diagnostics before choosing a fix.

For AB 1018 and AB 186, large candidate sets and completed rendering do not establish relevant retrieval. Read the selected passages against the question, then inspect branch ranks and Evidence Assembly omissions to distinguish weak candidates from selection loss. The earlier reference-query results are useful context, but this run did not revalidate them against the live graph.

## Limits

Five deliberately selected training cases cannot estimate the system's failure rate. There is no held-out sample, human answer label, calibrated judge, or citation-quality score. All five attempts are retained, including the case whose guidance failed. This run proves that the report exposes useful failure evidence; it does not establish that a voter received a supported answer.

The live graph can change independently of Git. The report's clean revision reconstructs this implementation and Data Set, while its recorded coverage describes the observed corpus at run time. An earlier exploratory report lacked structured retrieval evidence after guidance failure and remains disposable under `.scratch/chat-evaluation/`; use the linked report for review.
