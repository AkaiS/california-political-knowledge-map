# 13. Relevance filter evals (`pydantic-evals` + labeled dataset)

Status: ready-for-human

## Parent

[Scraping Pipeline PRD](../PRD.md)

## What to build

Stand up offline regression evals for the Relevance Filter using `pydantic-evals` under `tests/evals/`, so keyword-list and classification-logic changes can't silently regress.

Curate a benchmark dataset of ~100–200 representative URLs with titles and descriptions, manually labeled with ground truth (`RELEVANT`, `IRRELEVANT`, `INCONCLUSIVE`) — this labeling is the human-in-the-loop portion of this issue. Build an eval runner that scores the Relevance Filter against the dataset and reports Precision, Recall, and F1, executable via a dedicated script or test hook.

## Acceptance criteria

- [ ] A labeled relevance dataset exists at the PRD-specified location with human-verified ground truth spanning all three Relevance Statuses
- [ ] A `pydantic-evals` runner scores the Relevance Filter against the dataset and reports Precision, Recall, and F1
- [ ] The eval is runnable on demand via script or test hook without network access
- [ ] Baseline scores are recorded so future changes can be compared

## Blocked by

- [04-relevance-filter.md](./04-relevance-filter.md)
