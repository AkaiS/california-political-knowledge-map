# Product Requirements: Retry Layering and a Deps-Driven Coreference Resolver

Labels: ready-for-agent

## Problem Statement

Three unrelated failures are handled by one word. `retries` means "the model
returned unparseable output" on the coreference agents, "the Coreference Critic
disagreed" inside the resolver, and "the HTTP request failed" in the Story
Pipeline. The three budgets are configured separately, default to three, and
sit at different layers.

The pipeline's budget is at the wrong layer, and it is expensive. The Story
Pipeline retries whole stage calls, so a connection reset while the Coreference
Critic is judging the third round of Mention Spans throws away the annotation,
every located Mention Span, and every accepted verdict, then re-runs the Source
Article from the first token. The article eventually succeeds, so nothing in the
logs says that two full model passes were paid for and discarded.

The classification that drives it reconstructs typed information from strings.
`classify_api_error` walks the `__cause__` chain looking for a `status_code`
attribute, then falls back to substring-matching `"rate limit"` and `"timed out"`
against the exception's text; `get_retry_after` walks the same chain again
hunting for a header that httpx already parsed. Both re-derive what the HTTP
response carried.

Inside the Coreference Adapter, the domain logic is sound but its plumbing
obscures it. The numbered Source Article is pasted into three separate prompt
builders. A correction round is a fresh model call that re-states the article
rather than a continuation, so the annotator never sees the answer it is being
asked to correct. The loop's state — the observed Mention Spans, the outcome per
Mention Span identity, the accepted spans, the round count — lives in five local
variables whose last-write-wins invariant is documented only in a docstring. A
broad `except Exception` labels any escaping failure a
`coreference_validation_failure`, so a socket timeout that outlives its retries
is recorded in the Dead Letter Queue as a prompt-quality problem.

Finally, a Coreference Resolution Run whose Mention Spans all fail deterministic
validation is written straight to the Dead Letter Queue as
`all_mentions_discarded`. The annotator is never told that it cited a sentence
label that does not exist, even though that is precisely the kind of error it
could correct if asked.

## Solution

Put each retry at the layer that owns the failure it handles.

HTTP failures are retried by the HTTP client. The model factory builds every
Ollama model on an httpx transport that retries 429 and transport errors,
respecting the real `Retry-After` header. The retry then happens at the failed
request, so an interrupted Coreference Critic round resumes instead of the
Source Article restarting. Every LLM adapter in the repository inherits this by
construction, which is the same argument the Ollama null-content patch already
makes in that module. `classify_api_error` and `get_retry_after` are deleted.

The Story Pipeline keeps only what it owns: Article Status transitions, Dead
Letter Queue routing, and translating an exhausted transport retry into the
pipeline error categories that batch ingestion locks on.

The Coreference Adapter's agents take the Source Article and its numbered
sentences as dependencies, render the numbered article in one place, and treat a
correction round as a continuation of the annotator's own conversation. The
resolution loop's state becomes a model that owns the one-outcome-per-identity
invariant. Escaping exceptions are narrowed so that only model-output failures
are recorded as validation failures.

A Coreference Resolution Run in which no Mention Span can be located is offered
back to the annotator as a correction before it becomes a Dead Letter Queue
record.

## User Stories

1. As an AI engineer, I want an interrupted HTTP request to be retried at that
   request, so that a connection reset during the Coreference Critic's third
   round does not discard the annotation and every accepted verdict.
2. As an AI engineer, I want to stop paying for two complete Coreference
   Resolution passes when only one network call failed, so that local model
   time is spent on articles rather than on repeated work.
3. As a developer, I want the rate limit wait to come from the parsed
   `Retry-After` header, so that the delay is the one the server asked for
   rather than one inferred from the exception's text.
4. As a developer, I want to delete the exception-chain walking and substring
   matching in `classify_api_error`, so that no future failure mode depends on
   an error message containing the words "rate limit".
5. As a developer, I want every LLM adapter — Coreference Resolution, Entity
   Extraction, Selector Healing, and the Relevance Filter — to retry transport
   failures without each one opting in, so that a new adapter is covered by
   construction.
6. As an operator, I want the retry budget, the rate limit wait cap, and the
   request timeout to be settings rather than literals, so that I can tune them
   for a local Ollama host without editing code.
7. As a developer, I want one Ollama model and one connection pool to be shared
   across agent constructions, so that the retrying HTTP client's pool is
   actually reused rather than rebuilt on every call.
8. As an operator, I want an exhausted transport retry to still surface as a
   pipeline connectivity or rate limit error, so that batch ingestion's
   consecutive-failure lock keeps working unchanged.
9. As an operator, I want an article whose transport retries are exhausted to
   return to `UNPROCESSED` rather than being marked failed, so that it is
   retried on the next batch run.
10. As a developer, I want the Story Pipeline to be about orchestration, so
    that reading it tells me the stage order, the status transitions, and the
    Dead Letter Queue routing without a hundred lines of backoff arithmetic in
    the middle.
11. As an AI engineer, I want the numbered Source Article rendered in exactly
    one place, so that a change to how sentences are presented cannot apply to
    the annotator and miss the Coreference Critic.
12. As an AI engineer, I want the annotator's correction round to be a
    continuation of its own conversation, so that it sees the Mention Spans it
    previously returned when asked to correct them.
13. As an AI engineer, I want the Source Article and its numbered sentences to
    travel as typed dependencies, so that a prompt builder cannot be called with
    sentences that were split from different text.
14. As a developer, I want the Dead Letter Queue's agent metadata to come from a
    stable source, so that it does not break when instructions move and does not
    report a temperature that was never configured.
15. As an AI engineer, I want the resolution loop's state in one model that owns
    the one-final-outcome-per-Mention-Span-identity rule, so that the invariant
    is enforced rather than described.
16. As a developer, I want the discard proportion computed by the state that
    holds the outcomes, so that the metric cannot disagree with the outcomes it
    summarizes.
17. As a developer, I want the structured output re-validation removed, so that
    a Mention Span list guaranteed by the agent's output type is not validated a
    second time in three places.
18. As a developer, I want the unused text-only resolution helper deleted, so
    that there is one way to resolve a Source Article and it returns the
    Coreference Resolution Run.
19. As an AI engineer, I want a transport failure that outlives its retries to
    escape as a system error, so that it is not recorded in the Dead Letter
    Queue as a coreference validation failure.
20. As an AI engineer, I want a resolution bounded by request and token limits
    as well as by round count, so that an annotator returning hundreds of
    Mention Spans is stopped by a ceiling rather than by patience.
21. As an AI engineer, I want the critic round budget named for what it counts,
    so that it is not confused with the agent's structured-output retry budget.
22. As an AI engineer, I want an annotator that cites a sentence label that does
    not exist to be told so and asked again, so that a recoverable mistake is
    corrected instead of archived.
23. As an AI engineer, I want that correction bounded by the agent's
    structured-output retry budget, so that a persistently wrong annotator still
    reaches the Dead Letter Queue.
24. As an AI engineer, I want partial validation discards to stay discards, so
    that a single unlocatable Mention Span does not cost the neighbours that
    validated cleanly.
25. As an AI engineer, I want the Dead Letter Queue record for a corrected run to
    show that a correction was attempted, so that I can tell a first-response
    failure from an exhausted one.
26. As a developer, I want the existing per-Mention-Span behavior to be
    unchanged by all of this, so that the guarantees settled in ADR 0016 hold
    after the rebuild.

## Implementation Decisions

### Transport retries

- The Ollama model factory constructs an httpx `AsyncClient` whose transport is
  pydantic-ai's `AsyncTenacityTransport`, configured to retry `HTTPStatusError`
  and httpx transport errors, to wait using `wait_retry_after` capped at the
  configured maximum, to stop after the configured attempt count, and to
  re-raise. The client validates responses with `raise_for_status` so that a
  429 becomes a retryable exception.
- The client is passed to `OllamaProvider` as `http_client`. Ollama's
  OpenAI-compatible endpoint is reached through the provider, so this covers
  every agent in the repository without per-agent opt-in.
- A `TransportSettings` block is added to the settings module holding the
  attempt count, the rate limit wait cap, and the request timeout, each
  overridable by environment variable in the style of the existing settings
  blocks.
- The model factory memoizes by resolved model name and base URL, so repeated
  agent construction shares one provider, one client, and one connection pool.
  Today each `get_annotator_agent` call builds a new provider and a new
  connection pool.
- `classify_api_error` and `get_retry_after` are deleted from the exceptions
  module along with their tests. `classify_exception`, which routes Dead Letter
  Queue-worthy errors, stays.
- `PipelineRateLimitError` and `PipelineConnectivityError` remain. Batch
  ingestion's consecutive-failure locking branches on them and is unchanged.
  They are now raised at one seam: a wrapper that catches an exhausted
  tenacity retry and maps it by the final HTTP status — 429 to the rate limit
  error, anything else to the connectivity error.
- The embedding stage keeps a retry wrapper, because it is not an LLM call and
  does not pass through the model factory.
- `_execute_with_retry` is removed from the Story Pipeline. What remains is the
  stage sequence, the Article Status transitions, and the failure handler.

### Coreference agents and dependencies

- Both coreference agents declare a dependency type carrying the Source Article
  and its numbered sentences. The numbered article is rendered by one
  instructions function shared by both agents rather than by three prompt
  builders.
- The annotation prompt, the Coreference Critic prompt, and the correction
  prompt carry only their task-specific content: the request, the validated
  Mention Span list, and the rejected Mention Spans with the Critic's reasons.
- A correction round runs with the annotator's prior messages as history, so
  the annotator sees the Mention Spans it returned. This does not reduce token
  count — instructions are re-sent every request either way, and the history
  adds the prior response. It is accepted for the correction quality, not as a
  saving.
- The Dead Letter Queue's agent metadata stops introspecting the agent's private
  instructions attribute, which cannot render a dependency-taking instructions
  function. It reports the static instruction text, the prompt version, and the
  resolved model name. The hardcoded temperature is removed rather than
  reported, because no agent configures model settings.

### Resolution state

- The loop's state becomes one model holding the numbered sentence records,
  every observed Mention Span, the outcome map keyed by Mention Span identity,
  the accepted located spans, and the critic round count. It exposes the
  recording operations and the conversion to a Coreference Resolution Run.
  The last-write-wins rule, the exclusion of unrequested correction spans from
  the outcome map, and the discard proportion arithmetic all move onto it.
- The escaping exception handler narrows from `Exception` to the model-output
  failures: a Pydantic validation error and pydantic-ai's unexpected-behavior
  error. Anything else propagates and is handled by the Story Pipeline as a
  system error.
- `TypeAdapter(...).validate_python(result.output)` is removed at all three
  call sites; the agent's output type already guarantees the shape.
- The text-only `resolve_coreferences` helper is deleted. It has no callers and
  only forwards to the run-returning function.
- `max_retries` on the resolver is renamed to name the critic rounds it counts,
  and moves into a coreference settings block with the run's usage limits.
- Each resolution runs under a request limit and a total token limit.

### Correcting unlocatable Mention Spans

- The annotator gains an output validator that runs deterministic Mention Span
  validation against the dependency's Source Article. When the annotator
  returned Mention Spans and none of them can be located, it raises a model
  retry carrying the discard reasons, bounded by the agent's structured-output
  retry budget.
- Partial discards are unaffected: a response with at least one locatable
  Mention Span passes the validator, and its unlocatable spans remain recorded
  discards.
- An empty Mention Span list is not a retry. `no_mentions_returned` stays a
  distinct failure, because an article with nothing to resolve is a real
  outcome.
- `all_mentions_discarded` remains a failure type. It is now reached only after
  the correction budget is exhausted, and the Coreference Resolution Run's
  round count reflects the attempts.

## Testing Decisions

A good test here states an outcome the Coreference Adapter or the Story Pipeline
promises, and would survive a rewrite of how that promise is kept. It asserts on
the Coreference Resolution Run, the raised error and its failure type, the
Article Status transitions, and the Dead Letter Queue payload — not on sleep
durations, retry arithmetic, or the layout of a prompt string.

Three seams, two of them already in use.

- **The Coreference Adapter, driven by `FunctionModel` through `agent.override`.**
  The existing seam in `tests/test_coreference.py`,
  `tests/test_coreference_zero_survivors.py`, and `tests/test_mention_spans.py`.
  Every coreference change is observable here. The behavioral tests are binding
  and must pass unchanged: a rejected Mention Span does not cost its neighbours,
  a verdict for an unsent Mention Span cannot alter resolved text, a Mention
  Span with no verdict is discarded, a correction targets only rejected spans,
  and the three zero-survivor failure types are distinguished.
- **The model factory, with an injected httpx transport.** The one new seam. The
  factory accepts a transport so a test can supply `httpx.MockTransport`, and
  the assertion runs through a real agent call: a 429 carrying `Retry-After`
  followed by a 200 produces one successful run and one observed wait. This is
  the highest point at which transport retry is observable, and it exercises
  the real provider wiring rather than a client in isolation.
- **`StoryPipeline.run` with mock adapters.** The existing seam in
  `tests/test_batch.py`. It covers what the pipeline still owns: an exhausted
  transport retry surfaces as the right pipeline error with the right component,
  the article returns to `UNPROCESSED`, a coreference failure reaches the Dead
  Letter Queue and the article becomes `FAILED_DLQ`, and a Dead Letter Queue
  write failure becomes `SYSTEM_ERROR`.

Tests that are deliberately removed rather than migrated:

- The four backoff tests in `tests/test_batch.py` that patch `time.sleep` and
  assert delay sequences and call counts. They test how the pipeline waits.
  Their replacement asserts that exhaustion produces the right pipeline error
  and status transition.
- The `classify_api_error` assertions, which go with the function.

Tests that must be rewritten without a behavior change: the prompt assertions in
`tests/test_coreference.py` that read `messages[-1].parts[0].content`. Moving
the numbered Source Article into an instructions function moves it out of the
final user part, so those assertions read the whole rendered request instead.
The properties they check — the annotator sees the numbered sentences, the
Coreference Critic receives exactly one copy of the article, a correction round
names only the rejected Mention Spans — are unchanged and still asserted.

Prior art: `tests/test_coreference.py` for `FunctionModel` agent overrides,
`tests/test_batch.py` for pipeline runs against mock adapters, and
`tests/test_dlq.py` for Dead Letter Queue payload assertions.

## Out of Scope

- The Mention Span domain model, the numbered sentence splitter, the
  deterministic validation and substitution rules, and the per-Mention-Span
  Critic contract. ADR 0016 settled these and this project preserves them.
- Turning the resolution loop into a `pydantic_graph`. Its payoff is durable
  resumption across process boundaries, and a run is atomic in time: a retry is
  a new run, not a resumption. The state model gets the typed-state benefit
  without the node ceremony.
- Making the Coreference Critic a tool of the annotator. The Critic must see
  every validated Mention Span exactly once and the verdict matching must fail
  closed; letting the model decide when to call it gives up both.
- Async conversion of the Story Pipeline. The retrying client is async because
  the provider requires it; the pipeline stays synchronous.
- Setting a partial-discard threshold. The discard proportion is recorded and
  the threshold remains unset, as issue 05 of Coreference Resolution via Mention
  Spans left it.
- Any change to Entity Extraction, Selector Healing, or the Relevance Filter
  beyond inheriting the retrying transport.
- Evaluation of coreference quality, which is specified separately in the Model
  Evaluation initiative.

## Further Notes

Issue 01 is independent of the rest and is the largest win per line changed.
Issues 02 through 04 form a chain inside the Coreference Adapter.

Issue 02 is the one to drop if the correction-round token increase outweighs the
continuity on a local Ollama host. Issues 03 and 04 do not depend on the
dependency change, only on each other.

Issue 04 changes which runs reach the Dead Letter Queue, so it lands last and is
measured against the existing `all_mentions_discarded` and
`coreference-validation-failure` records under `.scratch/dlq/coreference/`.

No ADR is expected. ADR 0016 governs the resolution contract and this project
does not alter it; the retry layering is an implementation decision rather than
a durable architectural one. If the transport-owns-retries rule proves worth
stating for future adapters, record it then.

The Ollama null-content patch in the model factory is an operational constraint
that must survive the memoization change; it is applied at model construction
for the same reason the transport is.
