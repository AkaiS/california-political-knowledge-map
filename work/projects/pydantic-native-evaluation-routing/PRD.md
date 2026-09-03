# Product requirements: Pydantic-native evaluation routing

Labels: completed

## Problem Statement

Evaluation Runs maintain a custom Request Provenance subsystem alongside the
telemetry and report data already produced by Pydantic AI, Pydantic Evals, and
Logfire. A model request passes through capture context, retry state, a custom
schema, case aggregation, report serialization, and special failure-object
repair. The Evaluation Run therefore knows how request telemetry is captured
and reconstructed instead of simply executing a dataset and writing its report.

Most of that record duplicates existing facilities. Pydantic AI emits model,
response, usage, cost, and timing attributes. Pydantic Evals derives per-case
request, token, and calculated-cost metrics from the case span tree. Logfire
retains the operational detail needed to diagnose retries, failures, route
attempts, BYOK use, generation identity, and exact provider costs. Persisting a
second request record creates two authorities whose lifecycle and semantics can
diverge.

One durable fact remains useful in the committed Evaluation Run report: the mix
of effective response models and observed downstream providers used by each
successful Evaluation Case. That compact summary makes route changes visible in
a report diff without turning the report into another telemetry store.

## Solution

Remove Request Provenance as an application subsystem. Evaluation execution
continues through Pydantic Evals, model calls continue through Pydantic AI, and
request-level diagnostics continue through Logfire/OpenTelemetry. The engine no
longer opens a parallel capture scope, sequences request records, mutates failure
objects, or asks a provenance module to reconstruct what happened.

Add only the downstream-provider attribute missing from standard Pydantic AI
model-request telemetry. At case completion, derive a deterministic Model Route
Summary from the task execution span tree that Pydantic Evals already owns. Put
that summary in each successful case's report attributes. Group task-model
responses by Pydantic AI's effective response model and the observed downstream
provider, and record a request count for each pair.

Keep Pydantic Evals' built-in request, token, and calculated-cost metrics. Keep
OpenRouter's structured completion event as the operational home for BYOK use,
generation identity, route and application attempts, and exact charged or
upstream cost. Stop full HTTPX capture while retaining normal HTTP timing,
status, and error spans and Pydantic AI model-content instrumentation.

Preserve the Evaluation Run's existing outer provenance: commit, dirty-worktree
state, Gold Set, split, and structured Model Deployment. An interrupted or
exhausted run still writes no report. Historical reports remain unchanged.

## User Stories

1. As an AI engineer, I want each successful Evaluation Case to show its Model
   Route Summary, so that a report diff exposes changes in where task requests
   ran.
2. As an AI engineer, I want identical effective-model and downstream-provider
   pairs collapsed into one count, so that repeated task calls remain readable.
3. As an AI engineer, I want different route pairs to remain separate, so that
   fallback or mixed routing is not hidden by an aggregate total.
4. As an AI engineer, I want the response model to follow Pydantic AI's telemetry
   semantics, so that the report agrees with the framework that made the call.
5. As an AI engineer, I want the requested model used when Pydantic AI applies
   its response-model fallback, so that a provider's omitted response field does
   not create a second application rule.
6. As an AI engineer, I want an OpenRouter downstream provider recorded only
   when it was observed, so that configured provider order is never mistaken for
   evidence about the route that served a request.
7. As an AI engineer, I want a missing OpenRouter downstream provider to remain
   unavailable, so that the report does not invent provenance.
8. As an AI engineer, I want local model responses grouped with no downstream
   provider, so that the same summary shape works for every Model Deployment.
9. As an AI engineer, I want evaluator model calls excluded from Model Route
   Summaries, so that the summary describes the task under evaluation rather
   than the judge.
10. As an AI engineer, I want requests with no model response excluded, so that
    failed attempts do not masquerade as completed routes.
11. As an AI engineer, I want multi-round Coreference Resolution calls counted
    in their actual sequential task flow, so that annotation and criticism do
    not imply an impossible parallel ordering.
12. As an operator, I want concurrent Evaluation Cases isolated from one
    another, so that one case cannot receive another case's routes.
13. As an operator, I want Pydantic Evals' request, token, and calculated-cost
    metrics preserved, so that removing Request Provenance does not remove the
    framework's evaluation measurements.
14. As an operator, I want retries, errors, timing, BYOK use, generation
    identity, route attempts, and exact provider costs available in Logfire, so
    that operational diagnosis uses the existing telemetry system.
15. As an operator, I want OpenRouter's structured completion event preserved,
    so that provider-specific facts remain queryable without entering the
    committed report contract.
16. As an operator, I want HTTP status, timing, and error spans without blanket
    HTTP body and header capture, so that observability does not require copying
    every payload into low-level transport telemetry.
17. As a developer, I want route summaries derived from the case span tree, so
    that evaluation execution has one lifecycle and one source of model-call
    events.
18. As a developer, I want the custom provenance schema, context variables,
    sequencing, aggregation, and serialization repair deleted, so that the
    engine sends work through the framework instead of coordinating a second
    recorder.
19. As a developer, I want no request state machine or same-case parallel-order
    guarantee, so that the design does not solve concurrency that production
    task flows do not create.
20. As a developer, I want a single additional downstream-provider telemetry
    attribute, so that custom instrumentation is limited to the fact the
    standard framework does not expose.
21. As a maintainer, I want new reports to omit request-level provenance and its
    aggregate, so that the retired contract cannot silently survive through
    serialization.
22. As a maintainer, I want historical report files left untouched, so that an
    architectural change does not rewrite committed evidence.
23. As a maintainer, I want ADR 0017 and the domain glossary to name the Model
    Route Summary, so that code, reports, and architectural language share one
    boundary.
24. As an operator, I want interrupted or exhausted Evaluation Runs to keep
    writing no report, so that a partial run cannot appear complete.

## Implementation Decisions

### Ownership

- Pydantic AI and Logfire/OpenTelemetry own request-level model telemetry.
- Pydantic Evals owns per-case request counts, token usage, and calculated-cost
  metrics already derived from its span tree.
- The committed Evaluation Run report owns the outer run provenance and one
  compact Model Route Summary per successful case.
- Request Provenance is removed as a domain concept and implementation module;
  it is not renamed or retained behind another interface.

### Model route summary

- Each successful case adds `model_routes` to its report attributes.
- `model_routes` is a deterministic collection of entries containing the
  effective response model, observed downstream provider or null, and request
  count.
- Entries are grouped by the pair of effective response model and downstream
  provider and sorted deterministically before serialization.
- The effective response model is the value exposed by Pydantic AI telemetry.
  This deliberately includes Pydantic AI's fallback to the requested model when
  the provider omits a response model.
- The downstream provider is observed OpenRouter response data. It remains null
  for local deployments and when OpenRouter omits it; provider configuration is
  never used as a substitute.
- Only completed task-model responses represented beneath the case's task
  execution span contribute. Evaluator spans and requests without a response do
  not contribute.
- The summary is derived at the case lifecycle boundary from the existing span
  tree. No context variable, transport capture scope, or request-sequence field
  is introduced.

### Telemetry

- Model request spans gain only the observed downstream-provider attribute that
  is absent from standard Pydantic AI telemetry.
- Existing Pydantic AI instrumentation remains responsible for request and
  response model attributes, response identity, usage, calculated cost, and
  model content according to its configured policy.
- The structured OpenRouter completion event remains responsible for BYOK use,
  generation identity, downstream routing details, application attempts, and
  exact charged and upstream costs.
- HTTPX remains instrumented for ordinary request timing, status, and errors,
  but blanket `capture_all` body and header capture is removed.
- Telemetry is diagnostic and may have an operational retention policy. The
  committed report does not attempt to preserve all of it.

### Removal and compatibility

- Delete the custom request provenance schema, capture context, retry-state
  recorder, per-case request sequencing, aggregate builder, failure-object
  mutation, and failure serialization repair.
- New reports contain neither `request_provenance` nor its run aggregate.
- Preserve report fields for commit identity, dirty-worktree state, Gold Set,
  split, structured Model Deployment, cases, evaluator outputs, and Pydantic
  Evals metrics.
- Do not migrate or rewrite historical reports. Readers may encounter the old
  shape in repository history, but writers emit only the new shape.
- Preserve the rule that a failed, interrupted, or exhausted run writes no
  report. Model Route Summaries are not attached to failure objects.
- Production task ordering is unchanged. Coreference annotation, criticism,
  and correction remain sequential within a case; configured concurrency still
  applies across cases.

## Testing Decisions

- The highest testing seam is a completed Evaluation Run report. Drive real
  Pydantic Evals task execution through deterministic mock model transports,
  serialize the report, and assert the public report contract.
- Cover a single task response, repeated responses on the same route, mixed
  response routes, sequential multi-round Coreference Resolution, a local
  response, an OpenRouter response with no downstream provider, and Pydantic
  AI's response-model fallback.
- Run cases concurrently and assert that each report case contains only its own
  Model Route Summary. Do not add a same-case parallel ordering test.
- Include an evaluator that performs a model call and prove that its request is
  absent from `model_routes` while its evaluator output remains present.
- Include a request that produces no response and prove that it contributes no
  route. Preserve the separate assertion that a failed run writes no report.
- Assert that the completed report retains Pydantic Evals' request, token, and
  calculated-cost metrics and the existing commit, worktree, Gold Set, split,
  and Model Deployment fields.
- Assert that new reports contain neither request-level provenance nor a
  provenance aggregate.
- Add a focused telemetry test showing that an observed OpenRouter downstream
  provider is available on the model-request span used by the case span tree.
- Preserve focused coverage of the OpenRouter completion event's BYOK,
  generation, attempt, and exact-cost fields.
- Add a focused configuration assertion that HTTPX instrumentation no longer
  enables blanket capture while ordinary instrumentation remains enabled.
- Remove tests of private capture scopes, context variables, request sequence,
  custom aggregation, failure mutation, and synthetic same-case parallel
  ordering with the implementation they covered.
- Use no live model provider, Logfire project, or network request in the test
  suite.

## Out of Scope

- Rewriting historical Evaluation Run reports or completed project records.
- Replacing Pydantic AI's response-model semantics with an application-specific
  interpretation.
- Persisting retries, errors, timing, BYOK use, generation identity, route
  attempts, exact cost, or raw prompts and responses in Evaluation Run reports.
- Making Logfire a permanent versioning system or requiring its retention to
  match git history.
- Adding a request state machine, same-case parallel request ordering, remote
  run identity, polling, resumption, or finalization.
- Recording evaluator-model routes in the task's Model Route Summary.
- Writing reports for failed, interrupted, or exhausted runs.
- Changing Evaluation Gold Sets, Evaluation Splits, evaluators, task behavior,
  case concurrency, OpenRouter routing, retry policy, or admission control.
- A general observability redesign beyond the missing provider attribute and
  removal of blanket HTTPX capture.

## Further Notes

- ADR 0017 is amended in place because this change narrows the persistence
  boundary it already defines; it does not establish a separate architectural
  decision.
- The completed OpenRouter Model Deployments project records the history of why
  request provenance was introduced. Its completed artifacts remain historical
  evidence and are not rewritten by this project.
- The domain term is **Model Route Summary**. **Request Provenance** is an avoid
  term because it suggests a second request record beside telemetry.
- The implementation should prefer the public span and lifecycle surfaces
  exposed by Pydantic Evals and Pydantic AI. If the installed framework version
  cannot expose the required task response spans at the confirmed lifecycle
  seam, stop and document that concrete limitation before introducing another
  capture system.
