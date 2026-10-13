# Gemini Flash Lite trial evidence

Recommend a bounded trial with `OPENROUTER_MODEL=google/gemini-3.1-flash-lite`
and the exclusive provider order
`OPENROUTER_PROVIDERS=google-ai-studio,google-vertex/global`. Keep the dedicated
$5 monthly key cap, current prompts/validators, CPU embeddings and Jev retrieval.
This research made no paid request or configuration change.

## Primary-source support

Current official OpenRouter endpoint metadata lists both standard routes at
$0.25 per million input tokens and $1.50 per million output tokens. Both
advertise `tools`, `tool_choice`, `structured_outputs`, `response_format`,
`reasoning`, `reasoning_effort`, `temperature`, `top_p` and `max_tokens`. Forced
required/function tool choice is supported. Neither advertises `top_k`; the
application's current defaults omit it. The proposed routes avoid preview,
flex and priority tiers.
[Endpoint API](https://openrouter.ai/api/v1/models/google/gemini-3.1-flash-lite/endpoints).

The catalog identifies the canonical release as
`google/gemini-3.1-flash-lite-20260507`, with reasoning `mandatory: false`,
`default_enabled: true`, `default_effort: minimal`, and selectable efforts
`high`, `medium`, `low`, `minimal`.
[Official model catalog](https://openrouter.ai/api/v1/models).

OpenRouter defines `effort: none` as disabling reasoning and warns against it
for models whose metadata marks reasoning mandatory. This candidate is not
marked mandatory, although its enumerated effort list does not explicitly
include `none`. Acceptance of the exact disabled request therefore remains a
transport trial result, not a metadata guarantee.
[Reasoning contract](https://openrouter.ai/docs/guides/best-practices/reasoning-tokens).

OpenRouter documents per-endpoint structured-output support and
`require_parameters: true`, while cautioning that strict enforcement varies
by provider. Google documents enums, nulls and date formats in its schema
subset; application validation remains necessary.
[OpenRouter structured outputs](https://openrouter.ai/docs/guides/features/structured-outputs),
[Google structured outputs](https://ai.google.dev/gemini-api/docs/structured-output).

## Actual locked factory behavior

An offline real factory-to-Agent-to-HTTPX MockTransport probe used Pydantic AI
2.31.1, the proposed provider order and unchanged cloud request settings. It
emitted one request with:

- `reasoning: {effort: none}` from `thinking=False`. It does not emit
  `reasoning: {enabled: false}`.
- `tool_choice: required` and the output function's `strict: true`.
- Exclusive `only` and ordered providers, `allow_fallbacks: true` and
  `require_parameters: true`.
- The inferred `_OpenRouterGoogleJsonSchemaTransformer`, which retains
  Google's `nullable: true` representation for this genuine Gemini model.
- The unchanged five-value `reading_order` enum and default `relevance`.

The profile advertises tools, JSON Schema output, thinking support and strict
Google tool definitions; `thinking_always_enabled` is false. The existing
Gemma-only transformer override does not apply. A mocked valid response
produced typed `None` dates. This proves factory and validation behavior only.

The probe ran in repository test mode with a dummy key and disabled telemetry
exports. No credential was read. A bounded paid assessment and then the full
hosted question must establish actual route acceptance, enum/null compliance,
observed cost and complete application behavior. No prompt, validator or
retry relaxation is proposed.

## Actual assessment follow-up

The parent subsequently authorized a production assessment trial through the
owned deployment. It passed in 4.113 seconds with one framework request and one
HTTP 200 response, observed downstream provider Google AI Studio, typed null
dates and `reading_order: relevance`. The unchanged factory request's
`reasoning.effort: none` was accepted. No prompt, validator or output-retry
change was required. This is actual acceptance evidence for that one trial,
not a reliability evaluation.

The response cost field was zero; settled key usage remains pending. Published
standard endpoint pricing still applies, and this response does not establish
free inference. The parent stored the selected model/provider configuration in
Bottle Secrets. A same-code private restart will pick it up; full hosted
retrieval and guidance remain pending.
