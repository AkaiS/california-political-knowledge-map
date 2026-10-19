---
name: run-evaluation
description: Run this repository's model evaluations or summarize saved attempts. Use for RAG or chat eval requests, component evaluations, reruns, and explicitly requested mini sets.
---

# Run evaluation

Route the request to the maintained execution and reporting script. The script
owns Data Set validation, selection, persistence, and the summary.

1. Resolve the task from the request and current work. RAG retrieval, evidence,
   and generation use `rag`; question preparation or the whole Chat Session use
   `chat`. A named component uses its registered task. In a RAG review thread,
   “run the eval” and “rerun” mean `rag`. If the context leaves two tasks equally
   plausible, ask which task before starting model calls.
2. Use the complete established Data Set. Add `--sample N` or repeated `--case ID`
   only when the user explicitly requests that subset. “Just test on 1” means
   `--sample 1`. Time, cost, and debugging never authorize a smaller set. Carry
   an explicitly chosen deployment; the script otherwise uses local.
3. Run `uv run scripts/run_evaluation.py TARGET --plan` with those same arguments.
   Proceed when the plan matches the requested task and selection. A validation
   failure needs investigation; preserve the authored Data Set and reference
   artifacts. Rebuilding labels is a separate request.
4. Run the same command without `--plan`. Finish when the script has emitted its
   summary accounting for every selected ID, or report the execution error and
   the saved incomplete attempt. Use the summary's counts, unavailable-metric
   reasons, provenance, artifact path, and exact reviewer link in your response.
   A nonzero exit still carries reviewable results. For an existing attempt,
   use `uv run scripts/run_evaluation.py --report PATH`; repeat `--report` for
   one scorecard axis per attempt. JSON is the default output; `--format
   markdown` prints the scorecard for a person, and you quote it as printed.
   `--baseline` defaults to `auto`, the newest earlier Comparable Run saved beside the report; pass a
   report PATH to compare against that report, or `none` for no comparison.
5. Before presenting the reviewer link as live, verify the listening process
   serves the summary's absolute `reviewer_reports_dir`. An existing server may
   serve another checkout. Use `reviewer_command` to start the matching server;
   if its port is occupied by another directory, select a free port and regenerate
   the summary with `--report PATH --reviewer-port PORT`. Keep the existing server
   available. Until verified, describe the link as an address to use after starting
   that command; the summary's `reviewer_status` records this limit.

Full RAG run:

```bash
uv run scripts/run_evaluation.py rag
```

Explicit mini set:

```bash
uv run scripts/run_evaluation.py rag --sample 5 --seed 42
```

Read `uv run scripts/run_evaluation.py --help` for available task names and
arguments. The script resolves Data Set paths and checks benchmark membership;
keep those facts in code. If the required durable script is missing or the
requested task lacks one, create and test that script using the existing
Evaluation Engine before execution. Keep routing here and execution policy in
the maintained script.
