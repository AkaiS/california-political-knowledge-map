# OpenRouter Gemma profile review

Independent review of the Gemma-only schema adjustment in
[`utils/models.py`](../../../../src/knowledge_map/utils/models.py), using the
installed and locked Pydantic AI 2.31.1. No actionable findings.

The factory supplies one `ModelProfile` key, `json_schema_transformer`, only
when the OpenRouter model name, after removing the optional `~` alias marker,
starts with `google/gemma-`. It selects the library's
`OpenAIJsonSchemaTransformer`. Other OpenRouter models receive no override.
The local llama.cpp factory does not change.

I inspected the installed SDK's `Model.profile` and `merge_profile` implementations.
Resolution first merges `DEFAULT_PROFILE` and the provider-inferred profile,
then merges the supplied partial dictionary. The final supported native tools
remain the intersection of provider support and adapter implementation. The
override therefore preserves every other inferred capability rather than
replacing the entire profile.

The inferred OpenRouter Google transformer simplifies nullable unions and
removes string formats. The replacement preserves standard JSON Schema null
branches and date formats for the constrained Gemma route. QuestionAssessment's
Pydantic types and validators, authored prompts, output retry allowance and
provider policy remain unchanged.

## Independent verification

An isolated script compared each factory model's complete resolved profile to a
bare SDK model sharing its provider. Four Gemma names covered paid, free, `~`
alias and Gemma 3. Each differed only in `json_schema_transformer`. Two Gemini
names and one OpenAI name matched completely. The local Gemma profile matched
the unchanged llama.cpp profile completely.

The same script used a real Pydantic AI Agent and HTTPX MockTransport with the
factory model. Both date fields on the wire retained an `anyOf` containing JSON
`null` and a string with `format: date`, without `nullable: true`. Returned JSON
nulls became typed `None`. Empty strings still raised `UnexpectedModelBehavior`
with zero output retries. Both cases made exactly one mock request and retained
the exclusive `deepinfra/fp8` provider policy.

The final run used the repository's test mode to disable credential resolution
and telemetry exports. An earlier standalone invocation initialized existing
telemetry through the factory and attempted DNS-blocked exports; it was stopped
and rerun in test mode. No credential values were displayed and no paid model
requests were made.

The implementation worker's production assessment-agent regression and adjacent
factory suites also passed independently:

```sh
UV_CACHE_DIR=/private/tmp/ca-map-cloud-research-uv-cache \
  uv run --no-sync pytest -q \
  tests/test_openrouter_gemma_output.py \
  tests/test_openrouter_model_factory.py \
  tests/test_model_factory.py
```

Result: 54 passed in 1.80 seconds. Inspection confirmed the source diff is the
transformer import and the conditional profile argument only; the assessment
schema, production chat module and prompt resources have no diff for this fix.

## Limits

This review verifies factory scope, SDK merge behavior and schema/validation
behavior offline. It does not repeat the parent's paid assessment diagnostic or
establish every Gemma provider's JSON Schema support. The hosted deployment
still needs the patched release and its complete Source Guide checks.
