# Git is the evaluation versioning system

Superseded by [ADR 0024](0024-evaluations-preserve-the-selected-population-and-progress.md).
This document records the previous decision; ADR 0024 carries forward the
repository versioning boundaries and replaces failure disposal with explicit
population accounting and progressive persistence.

An Evaluation Data Set is a YAML file under `evals/gold/` or `evals/silver/`, according to whether a person or a model wrote its labels. An Evaluation Run is a command that builds a `pydantic_evals` `Dataset` from that file, executes it, and writes a JSON report to `evals/reports/<task>/`. Both files are committed. A Data Set's revision is a commit; a run's provenance is the commit it ran at, its structured Model Deployment, and each successful Evaluation Case's Model Route Summary. Pydantic Evals report metrics and Logfire/OpenTelemetry cover the operational request details. Comparing two runs is a diff of two report files. There is no Evaluation Ledger, no relational persistence of evaluation records, and no versioning mechanism authored for evaluation beyond the one the repository already has.

This supersedes ADRs 0005, 0006, 0007, 0008, 0009, 0010, 0011, and 0012 in their entirety. It also restates the decision recorded as ADR 0018 on `feat/evaluations` — Evaluation Data Sets are authored as version-controlled files — so that decision survives without porting the branch it was written on.

`pydantic-evals` remains the execution substrate, unchanged. It was never the problem: `engine.py` imports `Case`, `Dataset`, `Evaluator`, `ReportEvaluator`, and `EvaluationReport` from it and imports nothing from `store.py`. Everything this decision removes was built around `pydantic-evals`, not through it.

## Model Deployment, model routes, and telemetry

The report records a structured Model Deployment rather than a bare model
string. It identifies the selected deployment kind, requested model, effective
non-secret request settings, and, for OpenRouter, the ordered provider policy.
It contains no API key.

Each successful Evaluation Case records a Model Route Summary: deterministic
counts grouped by the effective response model and observed downstream provider
for task-model responses. The response model follows Pydantic AI's telemetry
semantics, including its fallback to the requested model when the provider omits
one. A downstream provider that OpenRouter does not identify remains
unavailable; it is not inferred from the configured route. The summary is
derived from the task execution's existing span tree. Evaluator model calls and
requests that produce no response are excluded.

Pydantic Evals owns the report's request-count, token-usage, and calculated-cost
metrics. Logfire/OpenTelemetry owns request-level diagnostics such as retries,
errors, timing, BYOK use, generation identity, route attempts, and exact charged
or upstream cost. Those diagnostics are operational telemetry, not a second
persisted evaluation record. The application adds only downstream-provider data
that the standard model-request telemetry does not expose.

This is evidence attached to the local report, not a second persistence system.
There is no remote run identity, remote job, polling, resumption, or finalization.
The local command writes no report for an interrupted or exhausted run; it is
rerun instead.

## Why now

The evaluation package is 9,008 of the 19,455 lines in `src/`. `store.py` alone is 3,995 lines and issues 21 `CREATE TABLE` statements, none of which exist in `document_store.db`: no Evaluation Run has ever been recorded by the system built to record them. Thirty-seven of the 91 terms in `GLOSSARY.md` are evaluation terms, and 40 of 92 on `feat/evaluations`. Seventy-one commits touched `src/knowledge_map/evaluation/` between 2026-07-10 and 2026-07-31, and none since.

Over the same period the pipeline those runs were meant to measure went to 14 `COMPLETED` and 59 `FAILED_DLQ` across the 73-article corpus. The evaluation contract was specified to a depth that outran every fact available to calibrate it, while the subject of the measurement stayed unmeasured and, on four articles in five, unfinished.

## What the ledger was solving, and why the repository already solves it

The superseded ADRs answer one question in eight forms: how does an evaluation record stay trustworthy as its inputs change underneath it? Immutable authored definitions, content-addressed artifacts, definition revisions, Frozen Aggregate Manifests, terminal checkpoints, and fenced Finalization authority are all mechanisms for reconstructing what was true at a past moment and proving nothing rewrote it since.

Version control does this. It does it for one author, over immutable-once-written records, with content addressing, atomic commits, and a reconstruction command. The ledger reimplemented it inside SQLite against a schema that had to be authored, migrated, and kept consistent by hand.

The properties the superseded ADRs required survive the change:

Immutability of authored definitions is a committed file plus the fact that a commit cannot be edited. Content addressing is the object hash. A run's exact inputs are recoverable by checking out its recorded commit. Atomicity of a run's evidence is one commit containing one report. Fenced Finalization has nothing left to fence, because a run either wrote its report file or did not.

Two properties do not survive, and both are deliberate. Automated Release Gate enforcement is removed; there is no release process and no CI to enforce it in. There is no resumption of an interrupted run; a run over a Gold Set of this size is re-run rather than resumed.

## Considered options

Keeping the ledger and writing the first Data Set against it was rejected. The obstacle to writing a Data Set has never been a missing mechanism — it is that every attempt to author one first required deciding how the authoring itself would be versioned, and that question has consumed three weeks and produced no cases. The mechanism is what stands between the author and the work.

Keeping the ledger dormant and unused, deleting nothing, was rejected. Nine thousand lines that no execution path reaches still cost every reading of `GLOSSARY.md`, every schema change that must stay consistent with a table nobody writes to, and every future decision that must be checked against eight ADRs describing a system that does not run.

Deleting evaluation entirely, including `pydantic-evals` and the Data Set format, was rejected. The goal that motivated all of this — knowing how well each non-deterministic component performs — is correct and unmet. What failed was the persistence layer, not the intent. `engine.py` and a YAML file are enough to start measuring this week.

Calibrating the ledger against real runs before deciding was rejected as circular. Calibration requires runs; runs require a Data Set; the Data Set has been blocked on the ledger.

## Consequences

`store.py`, `runs.py`, `preflight.py`, `bindings.py`, and `compatibility.py` are removed. `definitions.py` is reduced to the `EvaluationCase` shape `engine.py` imports. `suites.py` keeps evaluator configuration and loses ledger binding. `runner.py` loses its ledger half. `__init__.py` and `runner.py` are the only files importing `store.py`, so the largest removal touches two call sites.

Thirteen test files covering ledger behavior are removed with the code they cover: the 11 `tests/test_evaluation_*.py` files, `tests/test_metric_observation_ownership.py`, and `tests/conftest.py`, whose only contents were Data Set construction helpers.

`GLOSSARY.md` loses roughly 35 evaluation terms, among them Evaluation Ledger, Evaluation Finalization, Evaluation Finalization Attempt, Frozen Aggregate Manifest, Evidence Contract Version, Evaluation Checkpoint, Schema Reference, Resolved Schema Binding, Structured Metric Observation Materialization, Evaluation Artifact, Artifact Location, and Release Gate. Evaluation Data Set, Evaluation Case, Evaluation Split, Evaluation Suite, and Evaluation Rubric survive with their definitions narrowed to what a file and a report can carry.

Every `work/projects/` entry specifying the removed contract is closed as superseded rather than completed, including `shared-evaluation-contract`, `unified-evaluation-execution`, `evaluation-contract-hardening`, `case-evaluation-requirements`, `report-case-evidence-contract`, `structured-metric-observation-materialization`, `renewable-evaluation-finalization-authority`, and `gold-set-construction-factory`.

An Evaluation Case carries a stable authored `id`, written by hand or derived from the Source Article URL. This is the one guarantee the construction factory provided that a plain file does not get for free, and without it a regenerated Data Set silently breaks comparison against every earlier report. It is a required field, not a generated identity.

Evaluation Split stops being derived by hashing a case's business identity and becomes an authored field on the case. Hand-balancing replaces pinning.

A report is committed. This is what makes a past run recoverable, and a run whose report is not committed did not happen as far as the repository is concerned.

The custom Request Provenance schema, capture context, request sequencing,
aggregation, failure mutation, and serialization repair are removed. New reports
keep Pydantic Evals' built-in metrics and add only the per-case Model Route
Summary. Historical reports are not rewritten.

The removed code stays in this branch's history and on `feat/evaluations`, which is not merged and not deleted. Recovering any part of it is a checkout, so nothing here is a decision that cannot be reversed by reading it back out.

## Amendment: Gold Set was the wrong name for four of the five files

Recorded after the fact, because the original text of this ADR called every
evaluation file a Gold Set and only one of them ever was.

`evals/gold/relevance.yaml` is human-labeled and is the project's only Gold
Set. Coreference, extraction, Policy Area Classification and Topic Assignment
were all labeled by a model working to a written annotation guideline, which
makes them Silver Sets: a score against one is agreement with another model's
reading of that guideline, not with a person, and a case the annotator got
wrong scores a correct answer as a miss. Reading those numbers as though they
were human agreement overstates every one of them.

The umbrella term is now Evaluation Data Set; Gold Set and Silver Set are the
two kinds, and no term covers them loosely. The four silver files moved to
`evals/silver/`, `label_quality` is declared on the task and written into
every report, and reports written before this amendment were rewritten to
name the file they actually ran against. Earlier `evals/gold/` paths in
committed history are the old layout, not a claim that those labels were
human.

## Amendment: unlabeled cases precede answer evaluators

The Chat Session path now has an executable question set, but no reviewed
answer labels or settled failure categories. Its first Evaluation Data Set is
therefore under `evals/unlabeled/`. It reuses authored target questions as
training cases and records complete case outputs for human review. The task
has no answer evaluators and its report makes no answer-quality claim.

This extends Label Quality with `unlabeled`; it does not change the repository
as the versioning system. The YAML question set, JSON Evaluation Report, and
human review file can each be committed and compared through Git. Once reviews
identify repeatable failure modes, evaluators can be added against labeled
cases without treating the initial trace collection as a benchmark.

## Amendment: retain evidence for bounded retrieval decisions

Retrieval reports retain the first 50 unique Article Chunks per branch as
chunk ID, Source Article ID and best branch rank. Production fusion determines
eligibility from configured branch budgets but can use deeper ranks from other
branches for an eligible chunk. Reports retain only those additional ranks,
including explicit eligibility when configured production budgets exceed 50.
This reproduces current RRF scores and ordering without changing production
fusion or storing complete candidate tails.

Run configuration is stored once per distinct configuration. Case outputs keep
selected passages and citations, branch status, concise failure diagnostics,
useful preceding counts and model correction feedback. Deep candidate routes,
claims, repeated contributions, fused objects, catalogs and cumulative prompts
do not belong in the evaluation report. Full operational traces remain in
Logfire. Pydantic Evals continues to own execution, scores and usage metrics;
this is a task-specific projection in the existing report writer.

Recall cutoffs and reciprocal rank use a budget of unique chunks. Article-grain
cases measure article coverage inside that chunk budget, rather than searching
deeper for the first k distinct articles. Reciprocal rank is bounded to 50.
Reports record the metric definition so these corrected numbers cannot be
mistaken for the earlier identity-budget measurement.

The user requested compaction of the three initial, uncommitted retrieval
reports. Their originals are recoverable under `.scratch`, their migration
provenance records source hashes and the old metric definition, and changed
legacy scores are labeled outside current scores. The migration rescores those
same executions; it does not represent another model run. Other historical
reports are unchanged.

Larger retrospective candidate budgets, arbitrary discarded-candidate review
and every historical ranking experiment after graph changes require rerunning
retrieval. Those are accepted losses. Branch failures, reference misses within
budget, fusion loss and context-selection loss remain explainable.

## Amendment: RAG judgments have a focused review boundary

The reviewer has a separate RAG mode that projects each run to the approved
question, selected evidence, citations, final generation and retrieval
measurement specifications. It serves no intermediate pipeline records through
that mode's report API. Human labels are context relevance, answer relevance
and answer faithfulness, with an evidence note per axis. They are saved in a
separate `.rag-reviews.json` sidecar; whole-case chat critiques retain their
existing `.reviews.json` format. Both modes reuse the tested editing interface
for draft recovery, autosave, undo and navigation.

Missing judgment inputs remain unjudgeable. Missing reference metrics remain
unavailable. Reference precision@k measures matching chunk slots against the
same provisional silver labels used for recall, divided by k. It does not
claim exhaustive relevance judgments. Existing compact runs derive it from
retained ranks without rewriting the execution record. NDCG still requires
relevance grades absent from the initial references. Two-hop coverage is shown only for references
with two explicit evidence groups, with the reference-answer unit stated.
The reviewer does not combine context and generation from different executions.

Chunk relevance uses a separate query–Article Chunk view and annotation file.
A script freezes a balanced random sample from each attempted retrieval's fused
top ten. It preserves run hashes, ranks, text hashes and text observation origin;
text missing from the compact report can be loaded from the current graph with
that later observation recorded explicitly. The reviewer shows only question
and chunk text. High and Low labels export as judge-calibration examples; Defer
remains unresolved. Question groups travel with the export for disjoint judge
validation splits. Sampling and human labels do not overwrite retrieval metrics
or whole-context and generation judgments.

New retrieval evaluations also call the production final Chat Agent with the
approved question and that run's Evidence Package. The eval and Chat Session
share answer generation, citation validation and rendering. Question preparation
remains outside this focused task. Generation failures preserve retrieval
measurements and selected context. Compact reports retain generated guidance
and rendered output without duplicating the evidence execution under the answer.
