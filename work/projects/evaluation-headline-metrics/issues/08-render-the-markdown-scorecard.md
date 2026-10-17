# 08: Render the markdown scorecard

**What to build:** `Scorecard.to_markdown` renders one report or several, with
every number coming from the run report module. Several axes render as one row
per axis and never an overall score. The layout is the one the
[PRD](../PRD.md) specifies under Scorecard. Once every task declares a
headline, the registry's `headline` field becomes required.

**Blocked by:**
- 03, Record Coreference and Coreference annotator Headline Metrics;
- 04, Record Policy Area Classification and Topic Assignment Headline Metrics;
- 05, Record Retrieval Headline Metrics and show them in the RAG reviewer;
- 06, Record chat operational Headline Metrics;
- 07, Compare against the latest Comparable Run.

Labels: ready-for-agent

- [ ] The summary script accepts `--format markdown`, with JSON as the
  default, and repeated `--report`. It prints `to_markdown()` or `to_json()`,
  and its exit code is `Scorecard.exit_code` in both formats.
- [ ] A one-axis scorecard renders, in order:
  - the heading;
  - the population line;
  - the baseline line;
  - the primary and headline table;
  - the unavailable-metric lines;
  - the provenance line.

  Diagnostic rows render in a collapsed section.
- [ ] A multi-axis scorecard renders the per-axis summary table first, then
  each one-axis scorecard in argument order. An Unlabeled axis shows "no
  quality metric".
- [ ] A report without a headline renders its population block and its
  `NoHeadline` reason.
- [ ] The registry's `headline` field becomes required. Every registered task
  declares one.
- [ ] Snapshot tests of `Scorecard.to_markdown` cover one axis, three axes
  including chat, and a report without a headline.
- [ ] The summary script's single smoke test also runs `--format markdown`.
  It stays one test.
- [ ] Depth rule, tasks declare: every task touched supplies only a
  `HeadlineDefinition` built from the closed measure set and functions over a
  single case. No task defines a `ReportEvaluator`, builds table rows, or
  computes a population or failure rate.
- [ ] Depth rule, readers call: only the run report module classifies reports,
  accounts for the population, compares or renders. The summary script and
  the RAG reviewer gain none of that logic, and nothing outside the headline
  and run report modules parses table rows.
- [ ] Depth rule, two seams: tests cross only the engine-run seam and the run
  report module's interface (`ReportDocument.load` and `Scorecard.build`). The
  summary script's command line keeps its single smoke test and gains no other
  test. No test imports a measure's internals or adds a module-level test
  seam.
