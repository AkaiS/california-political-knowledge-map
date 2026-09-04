# 21 — Write no report after exhausted inference

**What to build:** An Evaluation Run that exhausts task or transport attempts
fails without writing a partial JSON report. The command must be rerun from the
Data Set, preserving the all-or-nothing report behavior in ADR 0017. Deliberate
terminal-only runs keep their existing no-report option.

**Blocked by:** 10 — Honor OpenRouter rate-limit timing for one request; 14 —
Select and record an Evaluation Run Model Deployment.

Labels: completed

- [x] Exhausted rate-limit attempts cause the Evaluation Run command to fail and create no report file.
- [x] Exhausted transport and task attempts also create no report file.
- [x] Successful runs still write one complete report with existing git, Data Set, Evaluation Split, task, and timestamp provenance.
- [x] The deliberate no-report option still prints a completed report without writing a file.
- [x] Tests start from an empty report destination and prove the absence of partial output after failure.
