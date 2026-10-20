# Evaluation reports freeze their run result

Accepted on 2026-10-16. Refines [ADR 0024](0024-evaluations-preserve-the-selected-population-and-progress.md).

An Evaluation Run's result is computed once, when the run completes, by its
task's Pydantic Evals `ReportEvaluator`. It is stored in the committed report as
a versioned table of Headline Metrics. Readers take the result from that table
and do not re-derive it from case scores. A report states a change only against
a Comparable Run: an earlier completed run of the same task over the same
selected case IDs, the same Data Set revision and the same headline version.
Headline versions are immutable. Changing a definition, an aggregation or a
population rule creates a new version, and reports under an older headline
version stay comparable only with each other.

Before this decision, every reader computed run results from case scores. The
console table, the summary script, the RAG reviewer, a one-off script and
hand-written documents each chose their own population, denominator and metric
subset. Two reports of the same run could disagree, and two runs over different
populations were compared as though the system had changed. Recomputing at read
time would keep old runs re-derivable under new definitions. A metric ledger was
tried and removed by ADR 0017. A frozen table gives up re-derivation in exchange
for one fixed meaning per number, and it uses the hook Pydantic Evals already
provides without adding any storage beyond the report file.
