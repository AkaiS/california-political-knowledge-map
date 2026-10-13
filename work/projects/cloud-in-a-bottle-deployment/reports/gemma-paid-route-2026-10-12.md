# Paid Gemma route evidence

The user's current choice is paid OpenRouter Gemma using the existing OpenRouter
key and credits, without a Google BYOK key. The deployed model is
`google/gemma-4-26b-a4b-it` with the exclusive provider `deepinfra/fp8`.
No configuration or credential was changed by this reviewer. Primary metadata
was checked across October 12–13, 2026; the report filename follows the deployment
work's original date.

## Endpoint support and prices

| Model | Exact endpoint | Input / million | Output / million | Required/function tool choice |
| --- | --- | ---: | ---: | --- |
| `google/gemma-4-26b-a4b-it` | `deepinfra/fp8` | $0.07 | $0.34 | Both supported |
| `google/gemma-4-31b-it` | `deepinfra/fp8` | $0.20 | $0.40 | Both supported |
| `google/gemma-4-31b-it` | `coreweave/fp4` | $0.10 | $0.34 | Both supported |
| `google/gemma-4-31b-it` | `deepinfra/turbo` | $0.09 | $0.34 | Neither supported |

The first three endpoints advertise `tools`, `tool_choice`, `structured_outputs`,
`response_format`, reasoning, temperature, top-p and token limits. Both DeepInfra
FP8 routes list 262,144 context tokens and 16,384 maximum completion tokens.
The alternative metadata was gathered before the user locked the model. It is
not a recommendation or authorization to switch. The cheaper 31B turbo endpoint
was unsuitable for the then-current required-tool wire.
Metadata does not establish model quality or strict tool-schema enforcement.
[Official 26B endpoint API](https://openrouter.ai/api/v1/models/google/gemma-4-26b-a4b-it/endpoints),
[official 31B endpoint API](https://openrouter.ai/api/v1/models/google/gemma-4-31b-it/endpoints).

## Historical output-tool wire

The earlier offline factory/Agent/MockTransport inspection confirmed the existing
Gemma-only `OpenAIJsonSchemaTransformer` correction applies. The 26B request
preserves genuine null/date unions and the five-value reading-order enum through
standard `$defs`/`$ref`. It emits `tool_choice: required`, `reasoning: {effort:
none}` and an ordered exclusive `only: [deepinfra/fp8]` policy with
`require_parameters: true`. The valid mock response produces typed `None` dates.

It does **not** emit `function.strict: true`. The installed Pydantic AI 2.31.1
transformer marks defaults and optional property omissions incompatible with
automatic OpenAI strict mode, so the default output wrapper leaves strict
unspecified. Earlier probe assumptions of strict mode and a directly inlined
enum were corrected after inspecting the actual wire. No source change was made.

DeepInfra documents schema enforcement for `response_format: json_schema`, but
the earlier application returned assessment through an output tool. That
documentation could not establish enforcement of that historical tool request.
The final release now uses strict native JSON Schema for assessment only.
[DeepInfra structured outputs](https://docs.deepinfra.com/chat/structured-outputs),
[DeepInfra tool calling](https://docs.deepinfra.com/chat/tool-calling).

## Actual candidate tests and remaining evidence

The parent's authorized 26B exclusive-DeepInfra assessments both passed on the
then-existing non-strict wire. Each returned `allowed`, actual JSON null dates,
typed `None` dates and `reading_order: relevance`, with one HTTP request.
Observed provider was DeepInfra and `is_byok` was false. Combined reported cost
was $0.00053218, also matching the exact funded key delta. The subsequent
full private HTTPS guide passed in 14.875 seconds with the expected AB 1751
article, reading directions and two Article Groups, no partial search or
disclosures, and successful ownership/history checks. It cost $0.00139204
through non-BYOK funding. Funded usage is $0.00448407, with $4.99551593
remaining under the verified $5 monthly limit; historical BYOK usage stayed
$0.00601500. Runtime peak was about 1.647 GiB with zero swap and OOM events.
These were prepublication trial snapshots. The user subsequently required
the selected 26B model to remain fixed; no alternate model or provider trial is
approved without direct user instruction.

The existing OpenRouter key is still necessary; no separate DeepInfra or Google
key is needed to buy shared inference using OpenRouter credits. The exclusive
DeepInfra policy excludes the Google providers and their BYOK route. Observe
`is_byok` and charged cost again during the complete question rather than
inferring billing solely from provider order. Preserve the dedicated $5 monthly
limit and avoid automatic fallback to a different model or unapproved provider.
[Provider allowlists](https://openrouter.ai/docs/guides/routing/provider-selection),
[OpenRouter credits and BYOK](https://openrouter.ai/docs/guides/overview/auth/byok).

This reviewer made only offline mock model requests and public documentation
reads. No paid call, account inspection, Logfire query, host mutation, prompt
edit, validator change or strict-output implementation was performed.

## Final deployed same-model integration

Public release `0444a3cffb7c1cb09f220fb7e36b8c45e5081563` uses only the
selected Gemma26/DeepInfra route. QuestionAssessment uses library
`NativeOutput(..., strict=True)`; guidance and all other deployment modes are
unchanged. One isolated actual native assessment passed before deployment.
The final anonymous guide retry then passed in 17.174719 seconds with the
expected linked AB 1751 article, a nonempty direction and two Article Groups,
completed search, no partial result and no disclosures. Owner reopening,
foreign-visitor 404 responses and persistent history passed. Peak memory was
1.745 GiB with zero swap/OOM events.

The final smoke charged $0.00135362. Funded key usage is $0.00629775;
historical BYOK usage is $0.00601500,
unchanged during the selected paid tests. Observed combined usage is
$0.01231275 and remaining monthly allowance is $4.98768725 with a $5 limit,
monthly reset and BYOK counting enabled.
This final native integration is acceptance evidence, not a model substitution.
[Strict integration review](strict-gemma-review-2026-10-13.md),
[hosted HTTP evidence](hosted-http-verification-2026-10-12.md).
