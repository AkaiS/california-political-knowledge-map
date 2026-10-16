# 06: Record chat operational Headline Metrics

**What to build:** A completed chat run on an Unlabeled Set records
operational Headline Metrics and says plainly that it has no quality metric.
Declined, Deferred and needs-edit questions are reported separately, and
latency is reported without a one-off script.

**Blocked by:** 01, Record Headline Metrics end to end for Relevance.

Labels: ready-for-agent

- [ ] Chat declares `chat-v1`. Its primary row is null with the reason
  "Unlabeled Set: no quality metric".
- [ ] The headline rows are:
  - completed-answer rate;
  - Declined, Deferred and needs-edit rates;
  - failure rate for each stage;
  - p50 and p95 task duration, with a case count;
  - `execution_failure_rate`.
- [ ] The completed-answer rule is the one the summary applies today.
- [ ] Question status comes from the recorded question preparation or
  assessment status, using the glossary's distinction between Declined and
  Deferred.
- [ ] The diagnostic rows are question-status rates by the cohort authored on
  each case, and branch outcomes by status.
- [ ] The summary takes chat's completed-answer and question-status counts from
  the table and no longer applies its own rules.
- [ ] Engine-run tests cover each question status, a stage failure, and
  durations of completed and failed cases.
