# 07: Compare against the latest Comparable Run

**What to build:** The evaluation summary finds the newest Comparable Run for a
report and states each Headline Metric's change against it. When no Comparable
Run exists, it says which conditions failed. A dirty worktree adds a caveat
rather than blocking the comparison.

**Blocked by:** 01, Record Headline Metrics end to end for Relevance.

Labels: ready-for-agent

- [ ] The summary accepts `--baseline auto|PATH|none`, defaulting to `auto`.
  `auto` picks the newest Comparable Run among the task's committed reports.
- [ ] Matching follows the glossary's Comparable Run: the same task, Data Set
  revision (compared by recorded hash), set of selected case IDs and headline
  version, in a completed run. Model Deployment, prompt digests and commit may
  differ.
- [ ] The summary gains a comparison block with:
  - the baseline path;
  - a status of `comparable`, `comparable_with_caveat` or `not_comparable`;
  - each failed condition;
  - a change for every primary and headline row.
- [ ] A dirty worktree on either side gives `comparable_with_caveat` and names
  which side is dirty.
- [ ] An explicit baseline that isn't comparable is reported with its failed
  conditions and no changes.
- [ ] Reports without a headline table or without a selection manifest are
  never Comparable Runs.
- [ ] Tests drive the summary's command-line entry point over saved documents.
  They reject each condition on its own, and accept a different Model
  Deployment and different prompt digests.
