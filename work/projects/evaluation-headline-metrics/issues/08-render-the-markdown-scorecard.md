# 08: Render the markdown scorecard

**What to build:** The evaluation summary renders a markdown scorecard for one
report or several, with every number coming from code. Several axes render as
one row per axis and never an overall score. The layout is the one the
[PRD](../PRD.md) specifies under Scorecard.

**Blocked by:** 07, Compare against the latest Comparable Run.

Labels: ready-for-agent

- [ ] The summary accepts `--format markdown`. JSON stays the default.
- [ ] A one-axis scorecard renders these parts in order:
  - the heading;
  - the population line;
  - the baseline line;
  - the primary and headline table;
  - the unavailable-metric lines;
  - the provenance line.
- [ ] Diagnostic rows render in a collapsed section.
- [ ] Passing `--report` more than once renders the per-axis summary table
  first, then each one-axis scorecard in the same order. An Unlabeled axis
  shows "no quality metric".
- [ ] Reports without a headline table render their population block, with
  the reason: predating Headline Metrics, or an incomplete run.
- [ ] Snapshot tests through the summary's command-line entry point cover one
  axis, three axes including chat, and a report without a headline table.
