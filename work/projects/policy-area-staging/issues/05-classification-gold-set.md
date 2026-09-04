# 05 — Policy Area Classification Silver Set and evaluation task

Labels: completed

## Parent

[Policy Area Staging](../PRD.md)

## What to build

Classification is measured rather than assumed. A Silver Set of twenty
article-level cases joins the evaluation registry as its own task, so a run
reports how well a model chooses an article's Policy Areas from the closed
vocabulary — the same way Coreference Resolution, the Relevance Filter, and
Entity Extraction are already measured.

The cases are drawn from the twenty Stories already in the coreference Silver
Set, so all four stages are measured over one population. Each case is one
Source Article: its resolved text as the stage sees it, and the areas the
article discusses as its expectation. The set is silver — labeled by
`claude-opus-5` against a written annotation guideline, as the coreference and
extraction sets are, with each case naming that guideline in its metadata.

Scoring is multi-label agreement over the vocabulary: precision, recall, and F1
across an article's areas, so a report distinguishes an article labeled with too
much from one labeled with too little. An article whose silver holds no areas and
whose answer holds none is a pass, not an unscoreable case.

The set is also the measurement 02 deferred: the number of areas per article is
recorded from what the twenty cases hold, so any future cap is set from a
distribution we measured rather than from a guess.

## Acceptance criteria

- [x] An annotation guideline for Policy Area Classification is written and lives
      beside the existing coreference and extraction guidelines.
- [x] A Silver Set file holds twenty article-level cases, each addressing a Source
      Article from the coreference Silver Set, with held-out and training splits
      and silver metadata naming the annotator model and the guideline.
- [x] The task is registered with its own input, output, and metadata types and
      the classification adapter as the callable under test.
- [x] Evaluators score multi-label precision, recall, and F1 over an article's
      areas; a case with no expected and no returned areas scores a pass.
- [x] A test loads the Silver Set through the registered task's own types and
      asserts the case count, the splits, and that every case id addresses a
      Source Article.
- [x] The observed areas-per-article distribution is recorded, and no maximum is
      introduced.

## Blocked by

- [02 — Policy Area Classification, once per Source Article](02-policy-area-classification-stage.md)
