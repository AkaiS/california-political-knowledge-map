# 14. Selector healer evals (HTML snapshot dataset)

Labels: ready-for-human

## Parent

[Scraping Pipeline PRD](../PRD.md)

## What to build

Stand up offline regression evals for the Selector Healing Pipeline using `pydantic-evals` under `tests/evals/`, so Generator/Critic prompt changes can't silently degrade selector quality.

Collect a snapshot dataset of historical publication HTML pages paired with their JSON-LD targets — gathering and verifying these snapshots is the human-in-the-loop portion. Build an eval runner that executes the healing loop against each snapshot and scores: Syntactic Validity of proposed selectors, Functional Success (title similarity >= 0.90, author match, date resolution against the JSON-LD targets), and Convergence Speed (Critic iterations <= 3).

## Acceptance criteria

- [ ] A snapshot dataset of HTML pages and JSON-LD targets exists at the PRD-specified location, covering multiple publications/layouts
- [ ] A `pydantic-evals` runner executes the healing loop per snapshot and reports Syntactic Validity, Functional Success, and Convergence Speed
- [ ] The eval is runnable on demand via script or test hook
- [ ] Baseline scores are recorded so future prompt changes can be compared

## Blocked by

- [08-selector-healing-pipeline.md](./08-selector-healing-pipeline.md)
