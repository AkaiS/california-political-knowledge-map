# Superseded by ADR 0017

Eight projects specifying the Evaluation Ledger and its contract. They are
archived as superseded rather than closed as completed: the work in them was
built and, in most cases, finished, and then removed by
[ADR 0017](../../../docs/adr/0017-git-is-the-evaluation-versioning-system.md),
which replaced relational persistence of evaluation records with two committed
file types — an Evaluation Data Set YAML and a run report JSON.

> **On the word "Gold Set" below and throughout this archive.** These projects
> used it for every evaluation file. Only `evals/gold/relevance.yaml` was ever
> gold: a person labeled it. Coreference, extraction, Policy Area Classification
> and Topic Assignment were labeled by a model against a written guideline,
> which makes them Silver Sets, and they now live under `evals/silver/`. The
> umbrella term is Evaluation Data Set. See the amendment to
> [ADR 0017](../../../docs/adr/0017-git-is-the-evaluation-versioning-system.md).
> The text below is left as it was written.

- **Case Evaluation Requirements** — semantic requirements on cases, satisfied
  by suite-owned evaluators, resolved into a plan before execution.
- **Evaluation Contract Hardening** — frozen manifests, terminal checkpoints,
  and secret-free configuration fingerprints.
- **Evaluation Gold Set Construction and Revisioning** — the construction
  factory, hashed split derivation, pins, and revision N+1 semantics. A case's
  split is now an authored field.
- **Renewable Evaluation Finalization Authority** — execution leases and
  fenced completion for interrupted runs. A run is now re-run.
- **Report Case Evidence Contract** — typed evidence for report-level cases.
- **Shared Evaluation Contract** — the record model underneath all of the above.
- **Structured Metric Observation Materialization** — schema-bound metric
  values persisted as typed observations.
- **Unified Evaluation Execution Path** — one execution seam across the
  in-memory and durable paths. There is now only the in-memory path.

What survives from all of it: `pydantic-evals` as the execution substrate, and
the decision that a Gold Set is authored as a version-controlled file.

The code is recoverable from this branch's history and from `feat/evaluations`,
which is neither merged nor deleted.
