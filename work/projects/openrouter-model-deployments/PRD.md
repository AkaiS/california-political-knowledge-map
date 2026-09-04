# Product Requirements: OpenRouter Model Deployments

Labels: completed

## Problem Statement

Evaluation Runs currently send every model request to a local llama.cpp server.
Coreference Resolution alone evaluates more than twenty Stories and may call an
annotator and Coreference Critic several times per case. Local inference makes
that feedback loop slow enough that prompt and task-decomposition experiments
are expensive to run.

The Story Pipeline has the same restriction. Its chat stages cannot use spare
remote capacity when local throughput is insufficient, even though Pydantic AI
already provides an OpenRouter integration. The shared model factory also still
uses `OLLAMA_MODEL` names left over from an earlier deployment. Chat no longer
runs through Ollama, and the stage-specific aliases imply distinctions that the
single local llama.cpp server does not provide.

Simply pointing the existing OpenAI-compatible client at OpenRouter would create
untrustworthy Evaluation Runs. OpenRouter may serve the same upstream model
release through different downstream providers, quantizations, and runtimes.
Its router can change models unless forbidden. The current report records only
a bare model string, so it cannot distinguish the local QAT Q4_0 GGUF from an
OpenRouter deployment of the same Gemma release, identify which provider served
a request, or show whether the configured Google AI Studio BYOK key was used.

Free and BYOK endpoints also impose rate limits. Case concurrency alone does not
coordinate callers after a `429`, and fixed token estimates would slow the run
while still failing to reproduce provider-specific token accounting. The project
needs reactive flow control at the shared request boundary, with bounded failure
behavior and enough report evidence to explain the time and cost of a run.

## Solution

Introduce two chat Model Deployments behind the existing model factory: local
llama.cpp and OpenRouter. Evaluation Runs use OpenRouter by default so prompt and
task-shape experiments can run with more remote capacity. The Story Pipeline
continues to use the local Model Deployment by default because it is unattended
and can take several hours. Both commands may select the other deployment
explicitly, and an Evaluation Run may override the configured model.

The two deployments use the same upstream Gemma release as a practical default,
but reports identify them separately. OpenRouter results are a fast directional
proxy for local behavior, not a claim of identical output. The local deployment
remains the authority when a change is eventually checked before use in the
Story Pipeline. This project provides the report evidence needed for that human
comparison; it does not automate the comparison or promotion process.

OpenRouter receives one fixed model, an ordered and exclusive provider allowlist,
same-model provider fallback, and a requirement that every selected provider
support the requested parameters. The already configured Google AI Studio BYOK
endpoint is expected to serve first. Approved OpenRouter-funded providers may
follow. The application records the actual route and `is_byok` result but never
stores either API key.

One process-wide reactive controller sits behind every OpenRouter model request.
Evaluation concurrency remains the operator's ceiling. When a `429` escapes
OpenRouter's provider routing, the controller pauses admission for every caller,
uses the server's reset information when available, and resumes with one probe.
It raises working concurrency after successes and lowers it after another rate
limit. Retries remain bounded. No proactive token counting, hard-coded provider
quota, or in-process spending ceiling is added.

Evaluation Run reports retain their git provenance and add the requested Model
Deployment, request settings, downstream route, token usage, charged cost,
and attempts. An interrupted or exhausted run still writes no report and must
be rerun, preserving ADR 0017.

## User Stories

1. As an AI engineer, I want Evaluation Runs to use OpenRouter by default, so
   that I can test prompt and task-decomposition changes without waiting on one
   local GPU.
2. As an AI engineer, I want to run the same Evaluation Data Set against the
   local Model Deployment, so that I can compare the proxy with the deployment
   used by the Story Pipeline.
3. As an AI engineer, I want OpenRouter and local reports to name different
   Model Deployments, so that sharing an upstream model release does not make
   them look interchangeable.
4. As an AI engineer, I want remote Evaluation Runs to preserve the authored
   Evaluation Cases, Evaluation Split, task, evaluators, and report format, so
   that changing inference capacity does not create a second evaluation system.
5. As an AI engineer, I want remote inference to remain inside the local
   `pydantic-evals` run, so that Data Set loading, scoring, and report writing
   stay versioned by git.
6. As an operator, I want the Story Pipeline to keep local chat inference as its
   default, so that an unattended batch does not begin spending remote capacity
   because configuration was added for evaluations.
7. As an operator, I want to select OpenRouter for a Story Pipeline command, so
   that I can use remote capacity when processing hundreds of Stories locally
   would take too long.
8. As an operator, I want embeddings to remain local, so that this change does
   not alter the Neo4j vector space or require the graph to be re-embedded.
9. As an operator, I want one configured local chat model and one configured
   OpenRouter chat model, so that every chat stage uses an intentional Model
   Deployment rather than a stale stage alias.
10. As a developer, I want every obsolete `OLLAMA_MODEL` configuration name
    removed, so that configuration names describe the llama.cpp and OpenRouter
    deployments that actually exist.
11. As a developer, I want deployment selection passed explicitly through the
    command assembly boundary, so that a report cannot record OpenRouter while
    an ambient local-model variable silently wins.
12. As an operator, I want a missing OpenRouter API key, model, or provider list
    rejected before the first case runs, so that configuration failures do not
    waste part of an Evaluation Run.
13. As an operator, I want one ordered provider list, so that Google AI Studio
    BYOK is primary and only providers whose rates I accept may serve as
    fallbacks.
14. As an operator, I want the provider list to be exclusive as well as ordered,
    so that OpenRouter cannot append an unapproved provider after the listed
    fallbacks fail.
15. As an AI engineer, I want OpenRouter forbidden from changing models during
    a run, so that every case in a report measures the requested upstream model.
16. As an AI engineer, I want provider fallback allowed for the same model, so
    that one unavailable host does not abort a long Evaluation Run.
17. As an AI engineer, I want every downstream provider to support all requested
    parameters, so that structured-output constraints are never dropped to keep
    a route alive.
18. As an AI engineer, I want local and OpenRouter requests to carry the same
    explicit sampling, reasoning, output-schema, and request-limit settings when
    both deployments support them, so that avoidable configuration differences
    do not obscure prompt effects.
19. As an operator, I want OpenRouter router metadata enabled, so that the report
    can identify the selected downstream provider, attempts, model, and BYOK
    status.
20. As an operator, I want the report to show whether Google AI Studio BYOK
    served each request, so that I can distinguish BYOK capacity from requests
    paid through OpenRouter credits.
21. As an operator, I want the report to show charged and upstream costs when
    OpenRouter supplies them, so that a provider comparison includes its actual
    price rather than a catalog assumption.
22. As an AI engineer, I want token usage recorded per model request and in
    aggregate, so that changes which improve quality by greatly increasing
    context remain visible.
23. As an AI engineer, I want actual provider data associated with the
    Evaluation Case and request sequence that produced it, so that a case-level
    anomaly can be traced to its route.
24. As an operator, I want case concurrency to remain an explicit ceiling, so
    that I control the maximum amount of work in flight.
25. As an operator, I want all OpenRouter callers in one process to share a
    pause gate, so that one observed platform limit stops new requests from
    every concurrent Evaluation Case.
26. As an operator, I want a `429` to extend but never shorten a current pause,
    so that concurrent failures cannot reopen the gate earlier than a previous
    response required.
27. As an operator, I want the controller to prefer the server's reset time,
    then `Retry-After`, then bounded backoff, so that it uses authoritative
    timing when OpenRouter provides it and still behaves when it does not.
28. As an operator, I want one request to probe the route after a pause, so that
    all waiting cases do not create another burst at the reset boundary.
29. As an operator, I want successful probes to restore concurrency gradually,
    so that the run seeks available capacity without assuming a fixed request or
    token quota.
30. As an operator, I want another `429` to lower working concurrency and pause
    admission again, so that the controller reacts to the capacity actually
    available to the configured route.
31. As an operator, I want the failed request to remain pending while the HTTP
    connection is released, so that it can retry without occupying a connection
    during the provider-directed wait.
32. As an operator, I want rate-limit retries to stop at a configured bound, so
    that a daily quota or unavailable route cannot leave a command alive
    forever.
33. As an AI engineer, I want an exhausted Evaluation Run to write no report, so
    that a partial population is not mistaken for a completed comparison.
34. As an operator, I want an exhausted Story Pipeline request to retain the
    pipeline's existing failure handling, so that a later batch may process the
    Story rather than silently losing it.
35. As an operator, I want authentication, credit, and invalid-request errors to
    fail immediately, so that the rate controller does not retry failures that
    waiting cannot fix.
36. As an operator, I want transport failures and retryable server errors to keep
    their existing bounded retry behavior without closing the global rate gate,
    so that only evidence of rate limiting pauses unrelated requests.
37. As a developer, I want local and OpenRouter model objects cached by their
    full Model Deployment identity, so that clients and connection pools are
    shared only when model, endpoint, route, and request settings agree.
38. As a developer, I want the llama.cpp compatibility profile and null-content
    patch isolated to the local deployment, so that local server workarounds do
    not silently define OpenRouter behavior.
39. As a developer, I want all chat-backed components to obtain models through
    the same factory, so that Coreference Resolution, Entity Extraction,
    Selector Healing, and the Relevance Filter cannot drift into separate
    provider implementations.
40. As a developer, I want deterministic tests to exercise real Pydantic AI
    agent calls against mock HTTP transports, so that provider and retry wiring
    are tested without live API calls.
41. As a maintainer, I want ADR 0017 and ADR 0019 reconciled with Model
    Deployments and the removal of Ollama chat configuration, so that the
    documented architecture matches the commands and reports.

## Implementation Decisions

### Model Deployment boundary

- The model factory becomes the single boundary for constructing local and
  OpenRouter chat models. Callers request a typed Model Deployment rather than
  relying on stage-specific environment lookup.
- A Model Deployment identifies the deployment kind, requested model, request
  settings, and provider-specific routing. It contains no API key and is safe to
  serialize into an Evaluation Run report.
- The local deployment uses the existing llama.cpp base URL, OpenAI-compatible
  client, schema-inlining profile, native structured output, and local retrying
  HTTP client.
- The OpenRouter deployment uses Pydantic AI's native OpenRouter model and
  provider. It does not reuse the local OpenAI-compatible provider merely
  because both ultimately use HTTP.
- The local null-content compatibility patch and llama.cpp model profile apply
  only to local models. OpenRouter uses its provider's own model profile.
- Model caching includes the full deployment identity: deployment kind, model,
  endpoint where applicable, provider order, and effective request settings.
  Secrets are excluded from both cache identity and diagnostics.
- Every chat-backed component receives or resolves the command-selected Model
  Deployment through this factory. Stage-specific `OLLAMA_MODEL` precedence is
  deleted.

### Commands and configuration

- Evaluation Run commands accept `--deployment local|openrouter` and default to
  `openrouter`. Their existing `--model` option overrides the model configured
  for the selected deployment and is the model recorded by the report.
- Story Pipeline commands accept `--deployment local|openrouter` and default to
  `local`. An explicit OpenRouter selection applies to every chat stage in that
  command. The Embedding Adapter remains local.
- Configuration supplies one local chat model and one OpenRouter chat model.
  The normal OpenRouter model is the free variant of the same upstream Gemma 4
  26B A4B IT release served locally.
- OpenRouter configuration also supplies its API key and one non-empty ordered
  provider list. Selecting OpenRouter without any required value fails during
  command setup, before Data Set loading begins execution or a Story changes
  status.
- All `OLLAMA_MODEL` and stage-specific `OLLAMA_MODEL_*` names are removed from
  runtime configuration, the example environment, documentation, tests, and
  error messages. No compatibility fallback keeps them active.
- Shared chat settings explicitly carry temperature, top-p, top-k, reasoning or
  thinking mode, and applicable output/request limits. Both deployments receive
  the same values when supported. OpenRouter routing requires support for every
  sent parameter rather than permitting a provider to ignore one.
- Google AI Studio quota values observed in the signed-in project are runtime
  facts, not application defaults or guarantees. The feature does not hard-code
  30 RPM, 16,000 input TPM, 15,000 RPD, or OpenRouter's free-tier limits.

### OpenRouter routing and BYOK

- One requested model is sent for the whole command. No ordered model fallback
  list is configured, and a route may never substitute another model silently.
- The configured provider list is sent as both the preference order and the
  exclusive allowlist. Same-model provider fallback is enabled within that set.
- Parameter support is mandatory for provider eligibility. If no approved
  provider supports the full request, the request fails.
- OpenRouter router metadata is enabled on every request. The application reads
  the selected provider, attempts, returned model, generation identity, and
  BYOK status when the response supplies them.
- The Google AI Studio key remains configured in OpenRouter's workspace BYOK
  settings. The application does not accept, store, or forward that Google key
  directly. OpenRouter's BYOK priority behavior is accepted as part of the
  route: AI Studio BYOK is tried before approved shared-capacity fallbacks.
- OpenRouter credit spending is allowed only through the approved fallback
  providers. There is no application spending ceiling or purchasing workflow.

### Reactive flow control and retries

- The OpenRouter HTTP path owns one process-wide rate controller shared by all
  model instances produced by the factory. Local llama.cpp requests do not pass
  through it.
- Evaluation `max_concurrency` remains the configured ceiling for concurrent
  cases. The controller maintains a working request-admission limit at or below
  that ceiling.
- A surfaced `429` closes the shared admission gate. Requests already accepted
  may finish, but no new OpenRouter request begins while the gate is closed.
- The controller derives the pause deadline from a valid rate-limit reset
  header when present, then from `Retry-After`, then from exponential backoff
  with jitter. Every wait remains subject to the configured retry wait cap.
- A new rate-limit response updates the shared deadline to the later of the
  existing deadline and the new deadline. It cannot shorten a pause already in
  force.
- The failed request releases its HTTP response and connection before waiting.
  It remains the same pending request attempt and retries at the transport
  boundary rather than restarting a Coreference Resolution Run or Story.
- When the deadline passes, one caller receives the probe permit. Other callers
  remain waiting. A successful probe begins gradual restoration of the working
  admission limit; another `429` closes the gate and lowers that limit.
- Successful requests continue raising the working limit until it reaches the
  operator's concurrency ceiling. The algorithm does not infer or estimate
  input token counts before sending a request.
- The existing configured transport attempt count and wait cap bound retry
  behavior. Exhaustion re-raises through the current Evaluation Run or Story
  Pipeline failure path.
- Authentication, authorization, credit, unsupported-parameter, invalid-model,
  and other non-retryable client errors fail immediately. Transport errors and
  retryable non-rate server errors use bounded request-local retry without
  closing the shared gate.

### Evaluation Run provenance

- A report records a structured Model Deployment rather than relying on its
  historical bare model field. Historical report files are not rewritten.
- The requested deployment evidence includes deployment kind, requested model,
  ordered provider allowlist, fallback and parameter-support policy, and all
  effective sampling, reasoning, output, and request-limit settings.
- Each model request record identifies its Evaluation Case and request order,
  returned model, selected downstream provider, BYOK status, route attempts,
  token usage, charged cost, upstream cost when available, generation identity,
  and retry count.
- The report also records aggregate input, output, reasoning, cache, and total
  tokens when available; charged and upstream costs; attempt count; and request
  counts grouped by downstream provider and BYOK status.
- Missing provider fields remain explicit unknown or unavailable values. The
  report never guesses a provider, quantization, cost, or BYOK result.
- Local reports identify llama.cpp as the deployment and record the same
  applicable request settings and token usage. Billed cost and BYOK status are
  unavailable rather than fabricated as remote values.
- API keys and authorization headers never enter the report, logs, exceptions,
  cache keys, or Model Deployment value.
- Report provenance continues to include commit, dirty-worktree flag, Data Set,
  Evaluation Split, task, and run timestamp. The report remains one committed
  JSON file under ADR 0017.
- An Evaluation Run that exhausts a task or transport retry writes no report.
  `--no-report` retains its current behavior for deliberate terminal-only runs.

### Documentation and domain language

- `Model Deployment` remains the canonical term for the concrete form of an
  upstream release invoked by an Evaluation Run. A local QAT Q4_0 GGUF and an
  OpenRouter endpoint are distinct Model Deployments even when they name the
  same Gemma release.
- ADR 0017 is reconciled with reports that record a Model Deployment and its
  request provenance. Git remains the only Evaluation Run versioning system;
  no ledger, resumption, or remote job identity returns.
- ADR 0019 is reconciled with two chat deployments. Its llama.cpp structured
  output decision remains the local behavior, while its deliberate retention
  of `OLLAMA_MODEL_*` names is reversed and explained.
- Operator documentation covers command defaults, deployment overrides,
  required environment values, OpenRouter BYOK routing, approved fallback
  providers, rate-limit behavior, and how to read local versus OpenRouter
  reports.

## Testing Decisions

- Good tests assert externally visible agent, command, and report behavior.
  They do not reach into private gate state, Pydantic AI internals, sleep-loop
  counters, or implementation-specific controller classes.
- The primary seam is a real Pydantic AI Agent using a model built by the shared
  factory, with an httpx mock transport in place of llama.cpp or OpenRouter.
  This is the highest existing seam that observes the real provider request,
  response mapping, retry transport, and agent result without live network use.
- At the primary seam, local requests prove that the llama.cpp endpoint and
  compatibility profile remain local-only. OpenRouter requests prove that the
  selected model, ordered and exclusive provider list, same-model fallback,
  required parameter support, router-metadata header, and aligned request
  settings reach the provider request.
- Concurrent agent calls through the primary seam prove that one `429` pauses
  every caller, a later deadline cannot be shortened, only one probe resumes,
  successful probes restore admission, another `429` lowers it, and exhausted
  attempts surface. Tests use controlled clocks and wait hooks rather than wall
  clock sleeps.
- Error examples distinguish platform rate limits, `Retry-After` responses,
  reset-header responses, missing-header fallback, transport failures,
  retryable server errors, invalid parameters, authentication failures, and
  credit failures.
- Response examples prove that returned model, provider, attempt metadata,
  `is_byok`, tokens, costs, and unavailable fields become normalized provenance
  without recording authorization data.
- Thin command tests cover the behavior outside the primary seam: Evaluation
  Runs default to OpenRouter, Story Pipeline commands default to local, both
  honor an explicit deployment override, model overrides bind verbatim, and
  missing OpenRouter configuration fails before inference.
- Thin report tests cover structured Model Deployment serialization, per-case
  request records, aggregates, secrets exclusion, historical git provenance,
  filename separation, `--no-report`, and the rule that an exhausted run writes
  no report.
- Existing deterministic task and Story Pipeline tests continue to override
  agents or inject adapters. They do not acquire real OpenRouter credentials or
  make live provider calls.
- Prior art is the model-factory test suite, which already runs real Agents
  against mock transports to observe retry behavior; the Evaluation Data Set
  suite, which already tests report provenance; and the command and Story
  Pipeline suites, which already test command assembly and adapter injection.

## Out of Scope

- OpenRouter's Batch API or any other queued remote-inference API.
- Remote execution, polling, resumption, or finalization of a whole Evaluation
  Run.
- Replacing `pydantic-evals`, duplicating Evaluation Suites in another language,
  or adopting OpenRouter Ori Eval.
- Remote embeddings, changing the Embedding Adapter, changing vector dimensions,
  or re-embedding the graph.
- Direct Google AI Studio as a third Model Deployment. The Google key stays
  behind OpenRouter BYOK.
- Model fallback. Only approved provider fallback for the fixed requested model
  is allowed.
- Proactive token counting, a fixed requests-per-minute scheduler, hard-coded
  Google or OpenRouter quotas, or an application spending ceiling.
- Coordination of rate state across processes, hosts, API keys, or other
  applications using the same OpenRouter account.
- Automated paired local and OpenRouter runs, score correction, statistical
  calibration, cross-run trend analysis, or a deployment-equivalence claim.
- Automated promotion gates or enforcement that a local Evaluation Run occurred
  before a prompt or task change reaches the Story Pipeline.
- Per-stage model or provider configuration. One command selects one chat Model
  Deployment for all of its chat-backed components.
- Reworking Evaluation Data Sets, Evaluation Suites, rubrics, or task-specific
  metrics.

## Further Notes

- OpenRouter currently exposes the same `google/gemma-4-26b-a4b-it` upstream
  release as the local model, but its documented endpoints do not expose the
  exact local QAT Q4_0 GGUF, llama.cpp build, chat template, or constrained
  decoder. OpenRouter Evaluation Runs are therefore a directional proxy.
- One paired local and OpenRouter run over more than twenty Coreference
  Resolution Evaluation Cases is one replicate over a varied population. It may
  describe the observed deployment difference, but it does not establish a
  stable score correction. This project records that evidence and leaves its
  interpretation to the operator.
- The user has purchased enough OpenRouter credits for the current higher daily
  free-model request allowance and has already configured Google AI Studio BYOK.
  The application relies on returned `is_byok` metadata rather than trying to
  inspect or manage the external credential.
- OpenRouter and Google publish rate limits as service and account properties
  that may change. Runtime `429` evidence remains authoritative for the reactive
  controller.
