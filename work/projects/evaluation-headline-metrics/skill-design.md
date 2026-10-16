# Skill design: report-evaluation

Companion to the [Evaluation headline metrics PRD](PRD.md). Parked on
2026-10-16: the PRD builds the scorecard layout below; the skill and its agent
slots are deferred until the maintainer has seen how evaluations come out once
the scorecard exists. This document designs the skill and the scorecard it
presents. The skill is not live.

## Where the variance comes from

An agent asked to report an evaluation today chooses three things itself: which
numbers to compute, which to show, and what to say about them. The first two
are the main source of variance, and they belong in code. The skill exists to
narrow the third.

So the split is:

- **The script owns every number.** `uv run scripts/run_evaluation.py --report
  PATH --format markdown` renders the scorecard from the report's headline
  table, the Comparable Run baseline and the population accounting.
- **The agent owns three bounded slots**: Reading, Cases to inspect and Open
  question. Each has a fixed size and a source it must cite.

The leading word throughout is _scorecard_: the script-rendered block the agent
copies verbatim.

## Invocation

Model-invoked. The maintainer asks for a report after most runs, and
`run-evaluation` must reach this skill when a run finishes. Both need a
description.

`run-evaluation` changes in two places so the two skills don't split one
branch between them:

- Its description drops "or summarize saved attempts". Reporting has one
  trigger, and it lives here.
- Its step 4 ends with "then report the run with `report-evaluation`". The rest
  of step 4 shrinks to finishing the run and capturing the report path.

## Scorecard layout

### One axis

```markdown
### <task> · <primary metric> <value> (<Δ vs baseline | no comparable baseline>)

<Label quality> Set · <scope> · selected <n> · scored <n> · failed <n> · unresolved <n>
Baseline: <report path> — <comparable | comparable with caveat: … | not comparable: …>

| Metric | Value | Baseline | Δ | Scored / selected | Aggregation |
| --- | --- | --- | --- | --- | --- |
| **<primary>** | … | … | … | … | … |
| <headline rows in declared order> |

Unavailable: <metric> — <reason>   (one line per null headline row)

Provenance: <commit>[ dirty] · <Model Deployment> · prompts <digests> ·
Data Set <sha prefix> · headline <version> · [report](<path>) · [trace](<url>)
```

Diagnostic rows render under a collapsed `<details>` block titled "Diagnostic
metrics", in the declared order.

### Several axes

A multi-axis report opens with one row per axis. It never shows an overall
score, because Gold and Silver numbers measure different things and the axes
don't share a unit.

```markdown
| Axis | Labels | Primary metric | Value | Δ | Scored / selected | Failure rate | Baseline |
| --- | --- | --- | --- | --- | --- | --- | --- |
| relevance | Gold | RELEVANT F1 | … | … | … | … | comparable |
| extraction | Silver | node F1 (pooled) | … | … | … | … | not comparable: Data Set changed |
| chat | Unlabeled | — | no quality metric | — | … | … | comparable |
```

After the table, each axis gets its own one-axis scorecard, in the same order.

## Agent slots

These follow the scorecard, once per report. In a multi-axis report there is
one set covering every axis.

1. **Reading**: at most three bullets. Each names a scorecard row and its value
   or Δ, then states what it means given the axis's label quality. A Silver
   result is agreement with the model annotator's reading of the guideline, so
   it shows direction of travel. A Gold result is agreement with a person. An
   Unlabeled run has operational counts only. When no comparable baseline
   exists, the first bullet says which condition failed and what would make the
   next run comparable.
2. **Cases to inspect**: at most three case IDs. Choose them, in this order,
   from execution failures, the largest per-case drops against the baseline,
   and the lowest-scoring cases. Before writing a case's line, open that case's
   output in the report and describe what it shows in one line.
3. **Open question**: at most one, and only when the scorecard raises something
   the maintainer must decide, such as re-baselining after a Data Set change.

Every number in the prose also appears in the scorecard.

## Draft SKILL.md

```markdown
---
name: report-evaluation
description: Report Evaluation Run results in this repository's fixed scorecard layout. Use when an evaluation run finishes, when asked to report, summarize or compare evaluation results, or when several axes were evaluated together.
---

# Report evaluation

The script renders every number. You copy its scorecard and write three bounded
slots around it.

1. Collect the report path for every axis in the request: from the run you just
   finished, from the user, or from the newest file in
   `evals/reports/<task>/`. Done when each requested axis has exactly one path.
2. Render the scorecard:

       uv run scripts/run_evaluation.py --report PATH [--report PATH ...] --format markdown

   Use `--baseline PATH` only when the user names a baseline. Done when the
   command exits and prints a scorecard for every path.
3. Copy the scorecard verbatim as the top of your reply.
4. Write the three slots defined in
   [skill-design.md](../../../work/projects/evaluation-headline-metrics/skill-design.md#agent-slots):
   Reading, Cases to inspect, Open question. Done when every number in your
   prose appears in the scorecard and every case line comes from reading that
   case's output.

When a report has no headline table, the scorecard says why: it either predates
headline metrics or comes from an incomplete run. Pass that reason on, report
the population block, and offer a full rerun with `run-evaluation`.
```

The slot rules live in this design until the skill lands. Then they move into
the skill folder as `SLOTS.md`, the pointer in step 4 is retargeted, and this
section becomes a link.

## Confirmed decisions

Confirmed by the maintainer on 2026-10-16:

- F1 is primary for relevance and coreference. Recall sits beside it as a
  headline row, which keeps the evaluators' "read recall first" guidance
  visible.
- Retrieval aggregates with the per-case mean, the IR convention.
- A dirty worktree adds a caveat to a comparison and does not block it,
  because 24 of 42 existing reports are dirty.
