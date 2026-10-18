# OpenRouter chat uses strict native structured output

Supersedes the OpenRouter paragraph of [ADR 0019](0019-llama-cpp-serves-chat-so-tool-calls-are-enforced.md),
which said OpenRouter uses its provider's structured-output behavior.

The model factory decides the structured-output mode for every chat Model
Deployment. Every OpenRouter model returns structured output as
`response_format: json_schema` with `strict: true`, so all properties are
required, defaults are removed and `additionalProperties` is false. Local models
already default to native output, as ADR 0019 records. Call sites pass bare
output types and never choose a mode. The Chat Agent allows one output retry.

## Why

On October 17, 2026, three of four Chat Sessions on the OpenRouter Model
Deployment (`google/gemma-4-26b-a4b-it` via `deepinfra/fp8`) failed at
guidance. The output mode was decided in two places: the local profile defaulted
to native, while OpenRouter relied on per-call `NativeOutput` wrappers. Guidance
overrides its output type at run time, which dropped the wrapper. The request
fell back to an output tool, which a hosted model may decline to call; Gemma
replied in prose or sent invalid arguments. With no output retry, each of those
replies ended the Chat Session.

## Considered options

Wrapping each call site in `NativeOutput(..., strict=True)` was rejected. It is
the arrangement that failed: any call site that overrides its output type can
silently lose the mode.

Leaving each provider on its default mode was rejected. An output tool is
optional for a hosted model to call, and the model then answers in prose.

## Consequences

- Providers without JSON Schema support are ruled out. `OpenRouterProviderPolicy`
  always sends `require_parameters`, so routing to such a provider fails rather
  than silently dropping the schema.
- Providers enforce schemas differently. llama.cpp compiles a JSON Schema subset
  to a grammar. Strict mode moves constraints it cannot express, such as
  `minLength`, `minItems` and `format`, into field descriptions. A provider may
  ignore `strict`, and a strict provider may reject a schema that another
  quietly relaxes. Pydantic validation stays the final check on every backend.
- Constrained output is not validated output, so the Chat Agent allows one
  output retry. A second rejection still ends the Chat Session.
- A free-form `dict` output field can only come back empty from an OpenRouter
  model. This is tracked as ME-07 in the [inbox](../../work/inbox.md).
- The rule reaches every model built by the factory on OpenRouter, including the
  Story Pipeline's Coreference Annotator, Coreference Critic and Extraction stages.
