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
Use `--deployment openrouter` to select one OpenRouter chat deployment for both
Coreference Resolution and Entity Extraction in that command. The Story
Pipeline command has no `--model` option; configure `OPENROUTER_MODEL` or
`LLAMA_CPP_MODEL` for the selected deployment instead.

Embedding remains local llama.cpp inference regardless of the chat deployment
selected for an Evaluation Run or Story Pipeline. It uses the separate
`LLAMA_CPP_EMBEDDING_BASE_URL` server and `EMBEDDING_MODEL` setting.

## Configure the deployments

Copy [`.env.example`](../.env.example) to `.env` and replace placeholders. The
local chat settings are `LLAMA_CPP_BASE_URL` (default `http://localhost:8080`),
`LLAMA_CPP_MODEL` (default `gemma4:26b`), `LLM_TEMPERATURE` (default `0`), and
`LLM_THINKING` (default `off`). Start the local chat server with
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

Each request's Request Provenance is associated with its authored Evaluation
Case and request order. Where the provider supplies the facts, inspect these
fields:

* `requested_model` and `returned_model` distinguish what was requested from
  what the provider reported;
* `downstream_provider`, `generation_id`, and `is_byok` describe the observed
  route and BYOK result;
* `input_tokens`, `output_tokens`, `reasoning_tokens`,
  `cache_write_tokens`, `cache_read_tokens`, and `total_tokens` preserve the
  separate token categories;
* `charged_cost` and `upstream_cost` retain the distinct cost facts;
* `route_attempts` is provider-reported route metadata when available, while
  `attempts` and `retry_count` describe application request retries; and
* `rate_limit_wait` records accumulated rate-limit waiting for that request.

The report also contains aggregates for available token and cost categories,
attempts, retries, waits, and request counts grouped by observed provider and
BYOK status. Missing values are explicit `null`/unavailable values: the report
does not infer a provider, BYOK result, token total, cost, route attempt count,
or wait. Local reports identify llama.cpp and may include applicable token
usage, but remote provider, BYOK, and billed-cost facts are unavailable rather
than fabricated.

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
