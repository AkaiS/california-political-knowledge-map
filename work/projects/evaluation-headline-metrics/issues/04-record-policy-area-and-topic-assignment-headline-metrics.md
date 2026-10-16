# 04: Record Policy Area Classification and Topic Assignment Headline Metrics

**What to build:** Completed Policy Area Classification and Topic Assignment
runs record pooled agreement Headline Metrics. Policy Area Classification also
reports a macro F1 across areas, so a common area can't hide failure on rare
ones.

**Blocked by:** 02, Pool set-agreement counts and record Extraction Headline
Metrics.

Labels: ready-for-agent

- [ ] Both tasks declare their own `-v1` headline versions.
- [ ] Policy Area Classification's primary row is pooled Policy Area F1. Its
  headline rows are:
  - pooled precision and recall;
  - label-macro F1;
  - per-case mean F1;
  - `execution_failure_rate`.
- [ ] Label-macro F1 is the mean F1 over the Policy Areas present in the
  selected cases' reference labels. Areas only predicted appear in pooled
  precision and in the per-area diagnostic rows.
- [ ] Policy Area Classification's diagnostic rows are per-area precision,
  recall and F1.
- [ ] Topic Assignment's primary row is pooled assignment F1. Its headline rows
  are pooled precision and recall, per-case mean F1 and
  `execution_failure_rate`.
- [ ] Both-empty cases keep their documented per-case pass and add zero to
  pooled counts.
- [ ] Engine-run tests cover both tasks, including a fixture where label-macro
  and pooled F1 disagree.
