# 07: Compare against the latest Comparable Run

**What to build:** The run report module finds the newest earlier Comparable
Run for a report and states each Headline Metric's change against it. When no
Comparable Run exists, it says which conditions failed. A dirty worktree adds
a caveat, never a block. All of this lives inside `Scorecard.build`; the
summary script only passes `--baseline` through.

**Blocked by:** 01, Record Headline Metrics end to end for Relevance.

Labels: ready-for-agent

- [ ] The summary script accepts `--baseline auto|PATH|none`, defaulting to
  `auto`, and passes it to `Scorecard.build` unchanged.
- [ ] A comparison checks six conditions independently and lists each one that
  fails:
  - task;
  - Data Set revision;
  - set of selected case IDs;
  - headline version;
  - a completed baseline with a table;
  - a selection manifest on both sides.

  Model Deployment, prompt digests and commit are never checked.
- [ ] `auto` considers only reports beside the current one with an earlier
  `ran_at`. It picks the newest that is `comparable` or
  `comparable_with_caveat`, with no preference for clean worktrees.
- [ ] With no candidate, the comparison carries the newest same-task report's
  failed conditions, or "no earlier run".
- [ ] A dirty worktree on either side gives `comparable_with_caveat` and names
  which side is dirty.
- [ ] Changes are computed for primary and headline rows only, and are null
  when either value is null.
- [ ] An explicit baseline that isn't comparable keeps its failed conditions
  and gets no changes.
- [ ] Summary-script tests over saved documents:
  - reject each condition on its own;
  - accept a different Model Deployment and different prompt digests;
  - prefer a newer dirty Comparable Run over an older clean one;
  - never choose a later report as the baseline.
- [ ] Depth rule, tasks declare: every task touched supplies only a
  `HeadlineDefinition` built from the closed measure set and functions over a
  single case. No task defines a `ReportEvaluator`, builds table rows, or
  computes a population or failure rate.
- [ ] Depth rule, readers call: only the run report module classifies reports,
  accounts for the population, compares or renders. The summary script and
  the RAG reviewer gain none of that logic, and nothing outside the headline
  and run report modules parses table rows.
- [ ] Depth rule, two seams: tests cross only the engine-run seam and the
  summary script's entry point. No test imports a measure's internals or adds
  a module-level test seam.
