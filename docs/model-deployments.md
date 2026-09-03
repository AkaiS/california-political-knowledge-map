# Model deployments

This guide describes the two chat Model Deployments that the application can
run. A Model Deployment is the concrete chat execution target selected by a
command: the local deployment is a GGUF served by llama.cpp, while the
OpenRouter deployment requests one named upstream model through OpenRouter's
ordered provider policy. They are distinct deployments even when they name the
same upstream release. An OpenRouter Evaluation Run is directional evidence
about the local deployment, not proof that the two behave identically.

The domain glossary in [`CONTEXT.md`](../CONTEXT.md) is the canonical vocabulary.

## Choose a deployment

`ca-map eval run <task>` evaluates against OpenRouter by default. Use
`--deployment local` to evaluate the local llama.cpp deployment. The command
accepts `--deployment local|openrouter`; the selected value is recorded in the
report. Evaluation also accepts `--model MODEL`. That value overrides the
selected deployment's configured model verbatim, so an empty or mistyped value
is not replaced by another environment setting.

`ca-map ingest` runs the Story Pipeline with the local deployment by default.
Use `--deployment openrouter` to select one OpenRouter chat deployment for
Coreference Resolution, Policy Area Classification, and Entity Extraction in
that command. The Story
Pipeline command has no `--model` option; configure `OPENROUTER_MODEL` or
`LLAMA_CPP_MODEL` for the selected deployment instead.

Embedding remains local llama.cpp inference regardless of the chat deployment
selected for an Evaluation Run or Story Pipeline. It uses the separate
`LLAMA_CPP_EMBEDDING_BASE_URL` server and `EMBEDDING_MODEL` setting.

## Configure the deployments

Copy [`.env.example`](../.env.example) to `.env` and replace placeholders. The
local chat target uses `LLAMA_CPP_BASE_URL` (default `http://localhost:8080`)
and `LLAMA_CPP_MODEL` (default `gemma4:26b`). Shared request configuration for
local and OpenRouter deployments uses `LLM_TEMPERATURE`, `LLM_TOP_P`,
`LLM_TOP_K`, `LLM_THINKING`, `LLM_REASONING_EFFORT`, `LLM_MAX_TOKENS`, and the
`LLM_TRANSPORT_*` settings. Blank optional values are omitted from requests.
Command assembly resolves these values into the Model Deployment before the
model factory builds a Pydantic AI model. Start the local chat server with
`scripts/llama-server.sh` and the local embedding server with
`scripts/llama-embed.sh`.

Selecting OpenRouter requires all three of these non-empty values:

* `OPENROUTER_API_KEY` authenticates the application to OpenRouter. The key is
  used by the provider client and is never part of a Model Deployment, cache
  identity, report, log, or exception.
* `OPENROUTER_MODEL` names the one upstream model requested for the command.
  Provider fallback never changes this model.
* `OPENROUTER_PROVIDERS` is a non-empty, comma-separated provider list. Its
  order is the preference order and the list is exclusive: OpenRouter may use
  only these providers, in this order, with same-model fallback. Every sent
  request parameter must be supported by the selected provider.

Missing or blank OpenRouter values are rejected during command setup, before an
Evaluation Gold Set begins executing or a Story changes status. The application
does not accept a direct Google AI Studio key.

## BYOK and funded fallbacks

Configure Google AI Studio BYOK in the OpenRouter workspace, outside this
repository. Put `google-ai-studio` first in `OPENROUTER_PROVIDERS` when that is
the preferred route, followed by only the approved fallback providers (for
example, `openai`). OpenRouter may use the approved fallback when the preferred
provider cannot serve the same requested model and parameters. Such a fallback
may consume OpenRouter-funded credits; the application does not choose a new
model, add an unapproved provider, or inspect the Google credential.

The returned `is_byok` value is the evidence for each request. A provider list
or a configured BYOK preference is not evidence that BYOK actually served a
request; use the report's observed value.

## Reactive rate limits

Rate control is reactive. A surfaced `429` closes one process-wide `OpenRouter
Admission Gate` for all OpenRouter Model Deployments. Requests already admitted
may finish, local llama.cpp requests bypass the gate, and no new remote request
starts until the pause expires. The failed response and connection are released
before the pending request waits.

The `OpenRouter Admission Gate` uses a valid reset header first, then
`Retry-After`, then bounded exponential backoff with jitter. A later response can
extend a pause but cannot shorten it. After the deadline, one `OpenRouter Probe`
is admitted; waiting callers remain blocked until that probe succeeds. Success
restores working admission gradually, while another `429` recloses the gate.
Transport and retryable non-rate server failures retain bounded request-local
retries, and non-retryable authentication, authorization, credit, model, and
parameter failures fail immediately.

Configured attempt and wait caps bound every retry. This is not a quota
scheduler: the application does not count tokens before sending, hard-code a
provider quota, or add an application spending ceiling.

## Read an Evaluation Run report

Completed reports are JSON files under `evals/reports/<task>/`. They retain the
Git commit, dirty-worktree flag, Gold Set, split, task, timestamp, and the
structured selected Model Deployment. An exhausted or interrupted Evaluation
Run writes no report; `--no-report` deliberately prints a completed report
without creating a file. There is no remote run identity or resumption.

Each successful Evaluation Case contains a `model_routes` Model Route Summary.
Each entry contains `response_model`, `downstream_provider`, and `request_count`;
entries count requests grouped by effective response model and observed
downstream provider, and are sorted deterministically. The response model
follows Pydantic AI's telemetry semantics, including its fallback to the
requested model when the provider omits one. A downstream provider is recorded
only when OpenRouter supplies it; local responses and missing OpenRouter
providers use `null`, and configured provider order is never substituted.
Evaluator model calls and requests that produce no response are excluded.

Pydantic Evals owns the report's request-count, token-usage, and calculated-cost
metrics. Logfire/OpenTelemetry owns request-level diagnostics such as retries,
errors, timing, BYOK use, generation identity, route attempts, and exact
charged or upstream cost. Those diagnostics are operational telemetry rather
than a second persisted report record. Historical reports may contain the
retired Request Provenance shape, but new reports emit only `model_routes`.

Do not read the route or a shared upstream model name as a deployment-equivalence
claim. OpenRouter can use a different provider, runtime, quantization, and
decoder from the local llama.cpp GGUF. Compare reports as observed evidence;
interpretation and any later paired calibration remain an operator decision.

## Deliberate boundaries

Embeddings remain local, and this feature adds no fixed request quota, token
scheduler, or application spending ceiling. It also adds no direct Google
deployment, remote Evaluation Run execution, remote job identity, polling,
resumption, or ledger. Git and the committed JSON report remain the evaluation
versioning system; a report that was not written and committed is not a
completed Evaluation Run.
