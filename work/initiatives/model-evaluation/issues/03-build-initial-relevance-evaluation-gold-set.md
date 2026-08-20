# Build the initial Relevance Filter Evaluation Gold Set

Labels: wayfinder:research, ready-for-human
Parent: [Repository-Wide Model Evaluation Strategy](../MAP.md)

## Question

What does the author have to label, and how do they assign splits, so that
`evals/gold/relevance.yaml` can distinguish a working Relevance Filter from one
that always answers `RELEVANT`?

## Blocking

- Blocks: Specify the Relevance Filter evaluation and comparison report.

## Decision

The Gold Set is [`evals/gold/relevance.yaml`](../../../evals/gold/relevance.yaml).
It exists, with 74 cases collected by `ca-map eval collect relevance` from the
rows the author labeled by hand while running the pipeline. It is not yet
usable, for one reason: 69 of the 74 cases are `RELEVANT`. A classifier that
returns `RELEVANT` unconditionally scores 93% on it.

The remaining work is labeling negatives. Everything else is done.

### What survives from the 2026-07-10 protocol

The binary labeling policy, unchanged:

- `RELEVANT`: the article substantively concerns California government,
  elections, ballot measures, political actors, public policy, regulation, or
  political influence relevant to the California Political Knowledge Map.
- `IRRELEVANT`: California politics or policy is absent, merely incidental, or
  the article is principally about another topic or jurisdiction without a
  substantive California political connection.

`INCONCLUSIVE` is an automated Relevance Status used to route an item for
review. It is never a human label, a Gold Set expected output, or a split.

The held-out access rule, unchanged: a `held-out` case's items, labels, errors,
and per-case results do not choose a model, prompt, threshold, feature, or
few-shot example. This is now enforced in code rather than by procedure —
`_few_shot_examples` in `src/knowledge_map/evaluation/tasks/relevance.py` draws
from the `training` split only.

### What ADR 0017 removed from it

The 200-case target, the two independent blind reviewers, the named
adjudicator, the chance-corrected agreement coefficient, the annotation-guide
pilot on 20 cases, the predeclared stratified sampling, the deterministic
group-disjoint split algorithm with a recorded seed, the frozen candidate
export, the manifest hash, the data statement, the access-controlled held-out
artifacts, and the immutable Evaluation Case revisions with fourteen fields of
provenance.

There is one author. The material is California news headlines. A second
reviewer is not available to recruit, so a procedure requiring two of them
describes work that cannot start. The provenance a case actually carries is its
URL as its `id`, the label, and the commit — which is what makes a report
comparable to an earlier report, and is all that ever got used.

### What to do

1. Label negatives until the Gold Set is closer to balanced. Roughly 30 more
   `IRRELEVANT` cases takes the majority-label score from 93% to about 70%,
   which is low enough that agreement starts carrying information. CalMatters
   sections outside politics — the environment, education, and economy stories
   already in `scraped_html_cache` — are where they are.
2. Re-run `ca-map eval collect relevance --force`, which re-reads the labels
   and reports the new balance. The `id` is the URL, so a case already in the
   file is updated rather than duplicated.
3. Assign splits by editing the file. Every case is `held-out` as collected.
   Move enough cases to `training` to few-shot the prompt — three per class is
   what `_few_shot_examples` takes — and leave the rest `held-out`.
4. Commit the file.

Every case is currently from CalMatters. A Gold Set of one publication measures
the Relevance Filter on one publication's house style; this is a known coverage
gap, not a blocker, and it closes when a second publication is registered.

## Acceptance Criteria

- [ ] `evals/gold/relevance.yaml` exists and every case validates against
  `RelevanceInput` and `RelevanceExpectation` when read. **Done 2026-08-19.**
- [ ] Held-out cases cannot reach the prompt that scores them.
  **Done 2026-08-19**, covered by
  `test_few_shot_examples_come_only_from_the_training_split`.
- [ ] No single label is more than 80% of the cases, so `ca-map eval collect`
  stops warning that the population makes a constant answer look good.
- [ ] At least three `RELEVANT` and three `IRRELEVANT` cases are assigned to
  `training`, so a run few-shots with the examples the production prompt uses.
- [ ] The file is committed.

## Comments

### 2026-08-19 — Rewritten after ADR 0017

The protocol this issue previously specified is preserved in git history. It
was written on 2026-07-10 and never executed; the blocker it named on
2026-08-04 was reviewer recruitment, which was never going to happen for a
single-author project.

Two findings from the 2026-08-04 comment stand and are unaffected by ADR 0017:

- `get_training_rows` in `classifier/src/classifier/trainer.py` filters to
  `relevance_label_source = 'LLM'`, which excludes every human label. The
  classifier cannot be fitted against the current table.
- `get_gold_standard_examples` in `src/knowledge_map/adapters/sqlite_db.py`
  selects human-labeled rows for the Relevance Agent's few-shot prompt with no
  split awareness. The evaluation path no longer calls it, but the production
  path still does, so the production prompt still draws its examples from
  whatever `scraped_html_cache` happens to hold — including cases the Gold Set
  reserves as `held-out`.
