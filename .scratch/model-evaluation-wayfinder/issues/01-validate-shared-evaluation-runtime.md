# Validate the shared evaluation runtime

Status: completed
Labels: wayfinder:research
Parent: [Repository-Wide Model Evaluation Strategy](../MAP.md)

## Question

Which combination of `pydantic-evals`, Pydantic AI, the current Logfire setup, CI artifacts, and relational persistence can implement the shared evaluation contract without duplicating capabilities or coupling suites to a provider?

## Blocking

- Blocks: Define the shared evaluation contract and record model.

## Findings

### Decision

Use the following composition for the shared evaluation runtime:

| Concern | System of record / implementation | Boundary |
| --- | --- | --- |
| Dataset and case execution | `pydantic-evals` `Dataset` / `Case` | A suite supplies a task callable and evaluators; it does not select a provider directly. |
| Model-backed task execution | Pydantic AI adapter owned by the component under test | The task receives a typed case input and delegates to an injected Pydantic AI agent/model configuration. |
| Deterministic scoring | `pydantic-evals` custom evaluators and report evaluators | Component-specific evaluators return named assertions, scores, or labels; report evaluators calculate aggregate metrics. |
| Trace and LLM telemetry | Existing Logfire setup, plus one evaluation-run span | The run span carries run/component/dataset metadata; Pydantic AI instrumentation supplies child model spans, token usage, cost, and latency. |
| Durable queryable records | A relational evaluation store, initially SQLite | Store dataset/case/run/artifact identities, configuration fingerprints, status, aggregate metrics, and case-level outcomes. |
| Large or sensitive material | Versioned files or CI artifacts, referenced by content hash and URI/path | Keep raw inputs, prompts, model outputs, and trace exports out of the relational tables by default. |
| CI transport | GitHub Actions artifact upload (or equivalent CI artifact store) | Upload the machine-readable report, human-readable summary, and failure manifest; do not make Logfire the CI pass/fail transport. |

This preserves provider independence: suites depend on a task protocol and typed inputs/outputs, while provider/model selection is run configuration. A Pydantic AI `TestModel`/`FunctionModel` seam can keep deterministic PR checks offline; release suites can inject the configured live model without changing cases or evaluators.

### Evidence from the current repository

- The project already depends on Pydantic AI 2.0.0 and Logfire 4.37.0 in `pyproject.toml` / `uv.lock`; Pydantic AI exposes `pydantic-evals` as an optional `evals` extra, but the evaluation package should be declared directly for an explicit, reviewable dependency.
- `src/knowledge_map/utils/telemetry.py` configures Pydantic AI and HTTPX instrumentation once and disables remote Logfire export during pytest. Evaluation code should use that setup and add a narrowly scoped `evaluation_run` span rather than creating a second telemetry configuration.
- The existing SQLite adapter uses plain relational tables and ISO text timestamps. It is suitable for local durable evaluation metadata and joins, but raw HTML, prompts, and model responses should follow the repository's retention principle and remain external to the evaluation database.
- There is currently no `.github/workflows/` directory, so CI artifact upload is a follow-on integration rather than an existing capability to reuse.

### Proposed shared runtime shape

```text
versioned gold set + suite config
            |
            v
  pydantic-evals Dataset.evaluate(task)
            |
            +--> Pydantic AI task adapter --> injected provider/model
            |
            +--> case evaluators + report evaluators
            |
            +--> Logfire evaluation_run span
            |
            +--> relational run/case/artifact records
            |
            +--> JSON/HTML summary + raw artifact manifest for CI
```

The shared task contract should therefore expose, at minimum, typed `inputs`, typed `output` (or a typed failure), dataset/version identity, component and suite identity, model/provider configuration fingerprint, and timing. Evaluators must not reach into provider-specific response objects; provider metadata is normalized by the task adapter into the run record.

### Persistence recommendation

Use relational links rather than a single JSON blob:

- `evaluation_datasets`: immutable dataset identity, component, version, source hash, and split.
- `evaluation_cases`: stable case identity, dataset foreign key, input/artifact reference, expected label/output reference, and metadata.
- `evaluation_runs`: run identity, dataset foreign key, suite/component, code/config/model fingerprints, execution mode, timestamps, status, and report artifact reference.
- `evaluation_case_results`: run and case foreign keys, status, duration, normalized output reference, evaluator scores/labels, error reference, and trace/span identity.
- `evaluation_artifacts`: content hash, kind, media type, retention class, and external URI/path.

The exact schema belongs to the next blocked issue. SQLite is adequate for local and single-writer CI runs; keep the adapter backend-neutral so a future PostgreSQL store does not change suite code.

### CI and release policy

- Pull requests: run deterministic/offline suites for affected components, persist a compact JSON report, and fail on configured regression thresholds.
- Release/nightly: run broad or non-deterministic suites with explicit model configuration, publish the full report and raw artifact manifest, and persist the run record.
- Logfire is for debugging and longitudinal observability; the serialized evaluation report and exit code are the authoritative CI gate. This avoids coupling correctness to network availability or Logfire retention.

### Constraints and open decisions for the next issue

1. Add `pydantic-evals` explicitly (prefer an evaluation/dev dependency group) and pin it through `uv.lock`.
2. Define the shared Pydantic models and protocols for dataset, run, case result, artifact reference, and normalized model metadata.
3. Define how a failed task is represented so evaluator failures and task failures remain distinguishable.
4. Define artifact retention/redaction rules before storing prompts or model outputs.
5. Define threshold configuration and baseline comparison semantics; do not hard-code quality floors until baseline runs exist.

## Sources

- [Pydantic Evals overview](https://pydantic.dev/docs/ai/evals/evals/) — `Dataset`/`Case` execution, evaluator/report model, serialization, and Logfire integration.
- [Pydantic Evals dataset API](https://pydantic.dev/docs/ai/api/pydantic_evals/dataset/) — typed cases, synchronous/asynchronous task evaluation, and dataset APIs.
- [Pydantic Evals evaluator overview](https://pydantic.dev/docs/ai/evals/evaluators/overview/) — deterministic, custom, score, label, and assertion evaluators.
- [Pydantic Evals report evaluators](https://pydantic.dev/docs/ai/evals/evaluators/report-evaluators/) — aggregate analyses such as confusion matrices and precision/recall.
- [Pydantic Logfire Pydantic AI instrumentation](https://logfire.pydantic.dev/docs/reference/api/logfire/) — `instrument_pydantic_ai`, custom spans, and captured model metadata.
- [Pydantic Logfire testing](https://logfire.pydantic.dev/docs/reference/advanced/testing/) — pytest-safe local span assertions and the default disabled remote export behavior.
- [GitHub Actions artifacts](https://docs.github.com/en/actions/tutorials/store-and-share-data) — uploading files/directories as CI artifacts.

## Outcome

The shared runtime is validated. The next issue can define the provider-neutral contract and relational record schema against this composition.
