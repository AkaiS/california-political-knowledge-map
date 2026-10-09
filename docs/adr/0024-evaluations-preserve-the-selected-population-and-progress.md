# Evaluations preserve the selected population and progress

Accepted on 2026-10-07. Supersedes [ADR 0017](0017-git-is-the-evaluation-versioning-system.md).

An evaluation must preserve what was selected and what happened, including failed
and interrupted attempts. Previously, the CLI discarded an entire returned report
when Pydantic Evals recorded a task failure, while exceptions caught inside a task
were saved. Small diagnostic runs and unlabeled chat runs also appeared alongside
full labeled RAG runs without a consistent selection and reporting workflow. These
differences made review depend on exception handling and agent choices.

## Execution and selection

Pydantic Evals remains the execution engine. Production task functions remain the
evaluated implementation. An evaluation skill routes the user's request and the
conversation context to maintained scripts; scripts validate the selection, run
the existing engine, and generate the standard summary. A missing script is
implemented and tested before execution rather than replaced by an improvised
evaluation. This adds no second evaluator framework or evaluation ledger.

An ordinary evaluation runs every case in the established Evaluation Data Set for
the chosen task. The RAG workflow uses the 25-case retrieval Silver Set and includes
final Chat Agent guidance. Whole Chat Session preparation is evaluated with the
separate chat task. A subset requires an explicit user request; its authored IDs,
sampling seed when applicable, and subset status are recorded. The chosen task,
population, Data Set identity, and Model Deployment are resolved before model
calls. Unexpected population changes require a deliberate update to the workflow.

## Progressive persistence

Before task execution, the report records the selected population and provenance.
Supported Pydantic Evals lifecycle hooks persist terminal case results, including
framework failures and evaluator errors. Each snapshot replaces the same report
file atomically, so a failed write leaves the previous complete JSON snapshot.
Writers serialize concurrent case completions. A returned framework report is
saved before the CLI exits nonzero for execution failures.

Run completion and task success are independent. The report distinguishes the
selected population, terminal outcomes, and unresolved cases; a run with all
selected cases accounted for may contain execution failures. A process that stops
without finalizing leaves a visibly unfinished snapshot. A handled interruption
is marked incomplete. Abrupt termination can lose work since the last persisted
terminal outcome, but it cannot turn the saved snapshot into a completed run.
There is no automatic resumption; another attempt creates another report.

The reviewer includes failed and unresolved cases and permits execution notes.
Context relevance, answer relevance, and faithfulness remain available only when
their required evidence exists. Declines and concise failure diagnostics remain
visible rather than being mistaken for missing review material. Operational
pipeline internals remain outside the focused RAG view.

## Reporting and retained decisions

One maintained summary accounts for the requested population and reports full or
subset status, terminal and unresolved outcomes, completed answers, failures by
stage, branch completion, and established retrieval metrics with their scored
populations. Missing scores remain unavailable with reasons. A failed case is
neither silently removed from accounting nor assigned invented metric values;
each metric retains its defined inclusion policy. Framework failures remain
distinct from task outputs containing stage failures and from evaluator errors.

The repository remains the versioning system. Evaluation Data Sets are authored
YAML with stable IDs and explicit splits. Gold Sets carry human labels, Silver
Sets model labels, and Unlabeled Sets inputs for error discovery. Scores against
these sets retain their different meanings. Run reports and human reviews can be
committed and compared through Git; uncommitted files lack durable repository
history. Provenance records the Data Set hash, code revision and dirty state,
Model Deployment, prompt versions, and observed settings. A live graph may change
independently of Git; recorded settings and coverage do not reconstruct it.

The other boundaries established in ADR 0017 remain: no database ledger, remote
run identity, execution lease, or finalization service; Pydantic Evals owns scores
and usage; Logfire owns operational traces. Compact retrieval reports retain
selected passages and graph facts, bounded branch ranks and the extra ranks
needed to replay production fusion, concise failures, and configuration identity.
Historical reports remain unchanged. Recall and reciprocal rank use unique-chunk
budgets; article-grain references apply that budget before deduplication. Reference
precision measures agreement with provisional labels, NDCG requires grades, and
two-hop coverage requires two explicit reference groups. RAG labels and sampled
chunk labels remain separate from whole-session reviews, and evidence and answers
are never combined across executions.

Rejecting failed reports prevented partial results from resembling successful
full runs, but erased the evidence most useful for debugging. Explicit population
and completion accounting provides that distinction while preserving the work.
Progress snapshots add local writes and require reviewer tolerance of incomplete
inputs; this cost is preferable to rerunning an evaluation merely to recover
already completed cases.
