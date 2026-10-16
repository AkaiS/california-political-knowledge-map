# 03: Record Coreference and Coreference annotator Headline Metrics

**What to build:** Completed Coreference and Coreference annotator runs record
the same agreement Headline Metrics, so their reports subtract. The full
Coreference loop also reports what the Coreference Critic's decisions were
worth.

**Blocked by:** 02, Pool set-agreement counts and record Extraction Headline
Metrics.

Labels: ready-for-agent

- [ ] Both tasks declare their own `-v1` headline versions. The primary row for
  each is pooled mention-span F1.
- [ ] Both tasks' headline rows are:
  - mention-span precision and recall;
  - B³ cluster F1 and canonical-entity accuracy, both pooled over every
    mention span both sides found, across all cases;
  - mention-span F1 as a per-case mean;
  - `execution_failure_rate`.
- [ ] Coreference's diagnostic rows are Critic rejection precision, rejection
  recall and kept-correct rate. Each is pooled over every judged critic
  decision across cases.
- [ ] On the annotator task the critic rows are present, each with a null value
  and the reason that the annotator task makes no critic decisions.
- [ ] Engine-run tests cover both tasks on shared fixtures, including a failed
  case and cases with no shared mention spans.
