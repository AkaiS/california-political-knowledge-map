# Strict structured output on the selected Gemma route

Independent review of installed Pydantic AI 2.31.1. The model stays
`google/gemma-4-26b-a4b-it`; the only provider stays `deepinfra/fp8`. No model,
provider, prompts, domain validators, output retries, source code, credentials
or host configuration were changed in this review. All requests below used an
offline HTTPX MockTransport and a dummy key; no paid calls occurred.

## Cause and supported seams

The existing Gemma profile selects the library `OpenAIJsonSchemaTransformer`.
Default `strict=None` checks compatibility without forcing conversion. Defaults,
optional properties and string length constraints make these schemas
incompatible, so `_customize_tool_def` resolves strict to false and the OpenAI
tool mapper omits `function.strict`. The Google strict-tool capability flag does
not control this OpenRouter/OpenAI mapping; changing it would fix the wrong seam.

The public API `ToolOutput(QuestionAssessment, strict=True)` forces the library
transformer to remove defaults, require all object properties and set
`additionalProperties: false`, then emits `function.strict: true`. It preserves
nullable date unions and the reading-order enum. Runtime output overrides would
also need wrapping if this caller-level approach were chosen.
[Pydantic AI output API](https://pydantic.dev/docs/ai/api/output/).

For coverage through the existing factory, the one-key Gemma-only profile
override can instead select a minimal library subclass:

```python
class StrictDefaultOpenAIJsonSchemaTransformer(OpenAIJsonSchemaTransformer):
    def __init__(self, schema, *, strict=None):
        super().__init__(schema, strict=True if strict is None else strict)
```

This uses the documented schema-transformer extension point. The SDK infers
`ToolDefinition.strict=True` from the resulting `is_strict_compatible` when the
original tool's strict value is None. Explicit `strict=False` is respected.
It covers both bare assessment output and the production guidance call's
runtime `output_type=RetrievalGuidance` without caller or authored-prompt edits.
Keep the override only in the existing Gemma selection branch and preserve all
other inferred profile fields. Review other Gemma tool schemas before assuming
this is compatible with every possible use of the shared factory.

Installed source inspected: `pydantic_ai/profiles/openai.py:480`,
`pydantic_ai/models/__init__.py:574,1718`, and
`pydantic_ai/models/openai.py:1678` under
`.venv/lib/python3.13/site-packages/`. These show strict conversion, compatibility
inference and emitted tool flags, respectively.

## Offline wire evidence

Four one-request factory/provider/Agent/MockTransport cases passed:

| Case | Actual wire | Typed result |
| --- | --- | --- |
| Explicit `ToolOutput(QuestionAssessment, strict=True)` | Output tool `strict: true` | QuestionAssessment |
| Strict-default transformer with bare QuestionAssessment | Output tool `strict: true` | QuestionAssessment |
| Strict-default transformer with runtime RetrievalGuidance | Output tool `strict: true` | RetrievalGuidance |
| Explicit `NativeOutput(QuestionAssessment, strict=True)` | `response_format.type: json_schema`, `strict: true`, no tools | QuestionAssessment |

Each emitted schema requires every property, forbids additional properties and
contains no `default` keywords. Valid actual JSON null dates pass the emitted
assessment schema; the string `"null"` for `reading_order` fails JSON Schema
validation. All profile fields except the intended transformer were equal to
the current factory baseline; the request model and exclusive provider stayed
unchanged. Mock success proves the client integration, not remote enforcement.

Strict conversion moves some unsupported wire constraints, including
`minLength`/`maxLength`, into descriptions. Existing Pydantic domain validators
remain authoritative and unchanged. Do not describe this as encoding every
domain invariant into provider-constrained decoding; chronology and policy
cross-field rules also remain application validation.

## Endpoint evidence and recommendation

The selected OpenRouter endpoint advertises tools and structured outputs, but
that metadata is not evidence of strict tool enforcement. DeepInfra's tool
calling page does not document a `strict` flag. Its structured-output page
explicitly documents `response_format: json_schema` with `strict: true` as
schema-constrained output. That is stronger documentation for native output,
but still does not establish the exact selected endpoint's behavior through
OpenRouter without an actual same-route test.
[Selected endpoint metadata](https://openrouter.ai/api/v1/models/google/gemma-4-26b-a4b-it/endpoints),
[DeepInfra tool calling](https://docs.deepinfra.com/chat/tool-calling),
[DeepInfra structured output](https://docs.deepinfra.com/chat/structured-outputs).

The initial factory-transformer candidate above was reviewed but not implemented
by this reviewer. The parent selected the more narrowly scoped
`NativeOutput(QuestionAssessment, strict=True)` candidate for assessment only,
using DeepInfra's better documented native JSON schema interface. Neither option
justifies a model change, weaker validators, prompt edits or more output retries.

## Assessment-only native follow-up

`get_chat_agent` installs no function tools or toolsets and defaults capabilities
to empty. `ChatSession._assess` uses that Agent's configured output without a
runtime override. A conditional native wrapper at construction therefore reaches
the actual assessment path. Guidance explicitly overrides output with bare
`RetrievalGuidance`, retaining the existing tool-output behavior on the same
Agent. No model-wide default mode or capability flag needs changing. Scope the
conditional to the selected OpenRouter Gemma deployment; all other deployment
output types remain unchanged.

Five additional offline factory/Agent/real `ChatSession._assess` cases passed.
A valid native text JSON response returned typed null dates. Invalid enum
`"null"`, date `"null"`, reversed chronological bounds and an unsupported status
without its required explanation each failed existing domain validation after
exactly one HTTP request. The failure cases raised `UnexpectedModelBehavior`
under unchanged `retries=0`; no output retry was added.

Each request retained the exact selected Gemma model, exclusive DeepInfra policy,
`require_parameters: true` and `X-OpenRouter-Metadata: enabled`. Requests emitted
`response_format: json_schema` with `strict: true` and no tools. The resolved
profile already supports native JSON Schema output and has
`native_output_requires_schema_in_instructions=False`, so this seam does not
inject a schema template into the authored instructions. The existing library
transformer handles strict-required fields, null/date unions and enum values.
It moves wire string-length constraints into descriptions as described above;
the original domain types, validators and cross-field policy remain authoritative.

These proofs cover SDK integration and production assessment validation only.
At that review stage, actual remote compatibility remained to be tested. The
parent's later actual same-route test and final deployment are recorded below.

## Independent implementation review

Reviewed the stable source worker patch in `core/chat.py` and both Gemma test
modules. The production conditional wraps QuestionAssessment only when the
explicit deployment is OpenRouter and its normalized model starts with
`google/gemma-`. Local, unspecified, Gemini and other OpenRouter deployments
retain the same output type. The source patch changes no model factory,
profile, settings, provider policy, authored instructions or retry settings.

Independently ran `uv run --no-sync pytest tests/test_gemma_native_assessment.py
tests/test_openrouter_gemma_output.py -q`: **19 passed in 2.16 seconds**. The real
factory/session tests prove strict native schema, required properties, explicit
nulls, date/enum rejection, unchanged question-policy/date context, fixed model
and DeepInfra routing, one request and zero output retries. Existing alias
coverage and invalid date-string regressions still pass. Runtime guidance
explicitly remains tool mode; other/local modes retain their baseline behavior.
No actionable implementation issue was found. The source worker later refined
only the native test fixture to supply required valid defaults while preserving
intentionally invalid fields; production code was unchanged.

## Final actual acceptance

One isolated actual strict native assessment passed using the same locked
Gemma26/DeepInfra route before commit and deployment. The full local suite
passed 1,799 tests with 77 skips and one existing sampling-temperature warning
in 72.35 seconds; 129 focused source-worker checks also passed.

The resulting public release `0444a3cffb7c1cb09f220fb7e36b8c45e5081563`
passed one final anonymous guide retry in 17.174719 seconds without owner
Authorization. It returned allowed/relevance assessment, the linked expected
AB 1751 article, a nonempty reading direction and two Article Groups, completed
search, no partial result and no disclosures. Owner reopening and foreign-
visitor 404 responses passed, with seven prior attempts preserved. The final
smoke cost was $0.00135362; peak memory was 1.745 GiB with zero swap/OOM events.
This verifies the selected integration journey; it does not claim every domain
invariant is encoded in provider constrained decoding or guarantee every future
model response. Existing application validators remain unchanged.
