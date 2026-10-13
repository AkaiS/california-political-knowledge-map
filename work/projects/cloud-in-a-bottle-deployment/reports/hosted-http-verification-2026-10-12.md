# Hosted HTTP verification

The owner-only hosted app passed its HTTPS, request-bound and visitor-isolation checks. After the schema-dialect correction, an initial reading guide returned two relevant articles with a conservative subtype-confidence abstention disclosed as partial. A second Gemma question failed on an invalid reading-order value. Switching the private runtime to Gemini then produced a **clean completed reading guide** with the expected AB 1751 article, nonempty guidance and no failed-search disclosure. Existing cookies, saved guides and failed-attempt history survived both controlled replacements. Newly observed Google BYOK charges are excluded from the current OpenRouter key limit; that budget gate remains for the parent to resolve before publication.

Checks ran on October 12, 2026 in America/Los_Angeles, corresponding to October 13 UTC in the proof timestamps. No browser was used. Production HTTP actions followed the Source Guides verification skill's feature map, adapted to the explicitly owned Bottle app through authenticated `bottle curl`. No local verification helper or existing local app was driven.

## Release and corpus

| Item | Confirmed value |
| --- | --- |
| Application revision | `daeda4fec637fe68819a8993c1acbf80d4feec7c` |
| AMD64 image | `sha256:1400ae1d062e62565cf994d60fdce88b2c27497487c5f7aa8fd344589d55c014` |
| Instance and app | `akaisenghor.bottle.cloud`, `california-knowledge-map` |
| HTTPS origin | `https://california-knowledge-map.akaisenghor.bottle.cloud` |
| Corpus release | `2026-10-12-real-corpus-01`, Neo4j Community 2026.07.1 |
| Neo4j dump SHA256 | `b9c57e38234afdd659f36eae2caca3f447d903fadcabd669effca696d3e00314` |
| Sanitized SQLite seed SHA256 | `ab0739c4236ad225fd57e9e46eebbd87b84f1cb23339f550a4befecd84fb1a2f` |
| Embedding artifact SHA256 | `b5ce9d77a3fc4b3b39ccb5643c36777911cc4eb46a66962eadfa3f5f60490d63` |
| Runtime ceiling | 5 GiB, three CPUs, one web worker |

The hosting worker confirmed all 383 tracked source files match the frozen revision. The apparent aggregate hash discrepancy was a verification sorting error: the helper sorts Path components, while the first comparison sorted strings. The correct source aggregate is `9f9f67e1eec0a8c5cf3fc3fffa8a52d398af964029a1be8b4c8f65d2e729a48a`. Independently, the HTTPS shell body matched the frozen Git HTML resource byte for byte.

The worker confirmed 98 Source Articles, 2,407 Article Chunks, 16 ONLINE indexes and the 768-dimensional COSINE vector space. The verifier's authenticated read-only graph query confirmed the actual AB 1751 article below with 32 Article Chunks. HTTPS coverage reported CalMatters publication dates from June 15, 2023 through September 5, 2026.

## HTTPS and ownership checks

| Action | Actual result |
| --- | --- |
| Owner-authenticated shell, liveness, readiness, coverage | HTTP 200 |
| Unauthenticated HTTPS shell | HTTP 404, owner-only routing preserved |
| Two independent visitor jars | Separate Secure, HttpOnly, SameSite=Lax cookies; empty initial guide lists |
| Foreign Origin submission | HTTP 403 |
| Body over 32,768 bytes | HTTP 413 |
| Question with 4,001 characters | HTTP 422 |
| Guide list after invalid submissions | Still empty |
| Guessed nonexistent guide read/update/cancel | HTTP 404 |
| Visitor B read/update/cancel of A's actual guide | HTTP 404 |
| Visitor A read/update/cancel of B's actual guide | HTTP 404 |
| Each visitor's saved list | Exactly its own guide |
| Two terminal GET reopenings per guide | Identical content, timestamps and attempt identity |

Read-only SQLite aggregate corroboration recorded two guides, two distinct owners, no unowned guides, two admissions and exactly two attempts: one completed and one failed. It selected no question text, owner hashes or credentials. Rejected requests created no additional attempt or admission.

## Authorized HTTP questions

1. Visitor A submitted `Who supported that bill?`. HTTP 202 created guide `b8fa8980-23c6-46b3-8b51-863db821866d`. Its original attempt finished in 1.923 seconds with `needs_edit`, a bill-name/number explanation, no articles and `search_details.completion: not_searched`. This mapped assessment journey passed.
2. Visitor B submitted `What should I read about AB 1751, the proposed $28 construction wage, and the disagreement between carpenters and other construction unions in California in 2026?`. The hosted graph contained [the relevant CalMatters article](https://calmatters.org/housing/2026/06/ab-1751-trades-carpenters-fight/). HTTP 202 created guide `03ae8218-8dc6-450b-8b1e-1e6c87df251f`. Its original attempt finished in 0.791 seconds with `assessment_failed`, no assessment or articles, and the public message `The question could not be assessed. Choose Retry to search again.` No retrieval occurred. This reading journey failed.

The hosting worker's exact scoped error extraction identified the literal string `"null"` in both `QuestionAssessment.publication_date_from` and `publication_date_through`, followed by `UnexpectedModelBehavior: Exceeded maximum output retries (0)`. Its initial summary called these empty strings based on the “input too short” error; inspecting the allowlisted date-field values corrected that summary. No credential, raw environment, prompt or unrelated log content was emitted. The failure was not relabeled as a completed reading journey.

Owned update/retry and duplicate-update POSTs were omitted under the initial two-execution allowance. A duplicate update racing completion could admit a third paid execution. The fast failed reading attempt also did not establish active-search cancellation. Cross-visitor cancellation rejection was verified; real owner cancellation remains unverified hosted.

## Budget and response evidence

The prepared in-app probe read the current web process's key only in private memory and requested the [documented current-key metadata](https://openrouter.ai/docs/api/api-reference/api-keys/get-current-api-key). It emitted only cap, period, remaining credit and usage fields. Before paid work, the response showed a $5 cap, monthly reset, $5 remaining and zero usage. BYOK usage was zero.

| Window or diagnostic | Observed OpenRouter cost |
| --- | ---: |
| Missing-reference HTTP assessment, current-key usage delta | $0.00024539 |
| Failed reading HTTP assessment, current-key usage delta | $0.00024022 |
| Initial two HTTP executions, settled total key delta | $0.00048561 |
| Isolated DeepInfra assessment with original transformer, response-reported cost | $0.00024022 |
| Isolated DeepInfra assessment changing only transformer, response-reported cost | $0.00028034 |
| Cumulative observed cost through both diagnostics | $0.00100617 |
| Corrected-release retry with two articles, settled key delta | $0.00131952 |
| Bill-focused failed assessment, settled key delta | $0.00023416 |
| Settled total through all four HTTP executions and two assessment diagnostics | $0.00255985 |
| Gemini isolated assessment, settled Google BYOK usage | $0.00092800 |
| Gemini clean HTTP retry, initial Google BYOK snapshot delta | $0.00128625 |
| Combined observed total at the first post-journey snapshot | $0.00477410 |
| Latest observed Google BYOK usage, later cap check | $0.00601500 |
| Latest combined observed OpenRouter and Google BYOK total | $0.00857485 |

After the initial two HTTP questions, the key had $4.99951439 remaining. The two isolated diagnostics were separately authorized by the parent within the same $5 monthly allowance and the $0.25 target. Their costs came directly from model responses, not a local token-pricing estimate, and the next current-key check confirmed their exact cumulative settlement. The final check after both corrected-release HTTP executions reported $0.00255985 used and $4.99744015 remaining, with the same $5 monthly cap and zero BYOK usage. TypeSafe probe token usage is reported separately; its account's monetary usage was not observable here.

The configured app requests `google/gemma-4-26b-a4b-it` through ordered exclusive providers `darkbloom,deepinfra/fp8`. HTTP guide responses do not independently identify their downstream provider. The isolated diagnostics observed response model `google/gemma-4-26b-a4b-it` and downstream provider `DeepInfra`. No assertion about the actual downstream provider of the original HTTP questions is inferred from configuration.

## Date-output diagnosis

The diagnosing-bugs feedback loop used the real `QuestionAssessment` validation seam. This fast command ran twice without paid requests:

```bash
UV_CACHE_DIR=/tmp/ca-map-uv-cache uv run --no-sync python \
  .scratch/hosted-http-verification-2026-10-12/date_schema_seam.py
```

It proves null dates validate, while empty strings fail both fields with `date_from_datetime_parsing`. Empty strings were the initial diagnostic input, not the actual value later extracted from the original trace. The isolated provider probe and regression also confirm that the captured literal string `"null"` fails the same date validation seam. Broad provisioning, authentication, corpus and retrieval investigation was skipped because the hosted trace already isolated the assessment validation failure, and retrieval had not begun. Repeated live fuzzing was outside the bounded request authorization.

Three ranked hypotheses preceded the paid differential probe: provider-specific output handling, a model-wide optional-date problem, and loss of null semantics in the outgoing schema. The first isolated probe retained the same model, public question, prompts, validators and zero output retries, and selected only `deepinfra/fp8` in its private process. It made one framework request and one HTTP request. HTTP 200 returned both date fields as the literal string `"null"`, which the domain schema rejected. It used 3,184 input and 51 output tokens.

The captured date schemas were `{type: string, nullable: true, default: null, description: "Format: date"}`. A standard Draft 2020-12 validator rejects JSON null under those schemas, while the original Pydantic schema accepts null. The installed OpenRouter provider selects its legacy `_OpenRouterGoogleJsonSchemaTransformer` from the `google/` prefix, including Gemma. That transformer simplifies nullable unions into Google's notation. Local Gemma already uses the library's `InlineDefsJsonSchemaTransformer`, which retains a real null branch.

A zero-paid library comparison confirmed the default OpenRouter transformation loses standard null semantics and `OpenAIJsonSchemaTransformer` preserves `anyOf` with `type: null`. The second isolated probe changed exactly that one profile field using the supported model constructor, preserving every other inferred capability and request setting. It returned `allowed`, raw JSON null in both fields, and typed Python None in both fields. Its actual wire schema contained `anyOf: [{type: string, format: date}, {type: null}]`. It made one framework and HTTP request, with 3,116 input and 183 output tokens. Total probe duration including dependency setup was 6.821 seconds.

These probes used the original guide's admission timestamp as a fixed reference time; the original Chat Session's exact subsecond reference time was not captured. They used the same hosted coverage and actual assessment call site. No retrieval, saved-guide write, persistent Secret change, schema normalization, prompt edit or retry-policy change occurred. The local correction now supplies only `json_schema_transformer=OpenAIJsonSchemaTransformer` for OpenRouter `google/gemma-` model names, including the supported `~` alias form. Every other inferred profile field remains intact. Gemini, other OpenRouter profiles and local Gemma keep their existing transformations. Prompts, domain validators and zero output retries are unchanged.

The new real factory-to-assessment-agent-to-MockTransport regression failed before implementation because the wire schema rejected JSON null. It then passed with a genuine null branch and typed None dates. The new module has ten cases covering wire behavior, model aliases, other inferred capabilities, untouched Gemini/OpenAI/Meta profiles, local InlineDefs behavior and rejection of empty/string-null dates without another output attempt. The targeted model, assessment, transport and date-bound suite passed **120 tests in 4.72 seconds**. Ruff passed the two source/test files. Red and green proof is retained in `gemma-regression-red.txt` and `gemma-regression-green.txt`.

Production code changes are limited to `src/knowledge_map/utils/models.py`; the regression is `tests/test_openrouter_gemma_output.py`. Independent review found no actionable issue and passed 54 adjacent tests. The parent's complete deterministic suite passed 1,790 tests with 77 skips. The parent committed and deployed the correction as described below, preserving the old failed attempt.

## Corrected release and actual retry

The hosting worker verified revision `a74ca13ffd6a6a6ddfd23568e8e9f26934d57286`, image `sha256:584327c5ce4cdb02e8835df9eb580e7416d99c68a183078774673aa178cd35da`, all 383 tracked files and aggregate source hash `7cf60672c3715e2612243655d9a2f45939b2caa88addb484de5df5220900efd1`. The app remained owner-only. The corpus and installed seed marker were unchanged. Before the retry, a GET with B's original cookie returned the original failed guide byte-equivalent as parsed JSON, and its list contained its own saved guide. The key confirmed a $5 monthly cap and settled prior usage of $0.00100617.

The verifier used the real HTTPS `POST /api/guides/03ae8218-8dc6-450b-8b1e-1e6c87df251f/update` with the existing cookie and `{}` body. HTTP 202 admitted exactly one new attempt, `369fdce2-9bec-4092-bc9a-155e431fc3d4`, from `2026-10-13T02:29:16.092150Z` through `02:29:28.088240Z`, lasting 11.996 seconds. Polling returned `completed`, an `allowed` assessment and these linked articles:

- [A California housing bill would raise wages to $28. Why do some unions hate it?](https://calmatters.org/housing/2026/06/ab-1751-trades-carpenters-fight/), published June 4, 2026.
- [A $28 minimum wage for California construction workers is dead — killed by construction workers](https://calmatters.org/housing/2026/06/construction-minimum-wage-fail/), published June 25, 2026.

Both articles had nonempty reading directions and CalMatters publication metadata. Two Article Groups covered the union disagreement and the wage proposal. The response included relevance and publication orders, collection bounds, `included_articles: 2`, and a bounded selection with omitted material. No verified highlights were available. HTTP proves saved response data; browser rendering, reading-view interaction and opening remote article tabs were not exercised.

The actual response also had `partial: true`, `search_details.completion: partial`, and the disclosure `Part of this search failed. Available reading is retained, but this search is incomplete.` This is not recorded as a clean full-search pass. Code inspection ties these markers to at least one failed expected retrieval branch; the HTTP contract does not expose which branch. The hosting worker's scoped stdout inspection found no branch diagnostic, exception, provider or usage field. Branch diagnostics are recorded as Logfire span attributes. The direct diagnostics below reproduced a conservative structural-selection abstention. No second paid HTTP retry has been submitted.

Typed saved-guide assertions confirmed the same question, guide ID and creation time; a new completed attempt; an allowed assessment; the expected corpus article; nonempty directions; and the included-article count. The validator excluded only the documented web-computed `publication_orders` field. Two subsequent owner GETs exactly matched the terminal JSON. Visitor A again received 404 for read, update and cancel. Read-only SQL confirmed two guides, two owners, no unowned guides, three admissions, and three attempts (two completed, one failed). The original failed attempt `fe7bfb77-79e3-49bd-a38b-9c53a2ec22ae` remains stored unchanged alongside the new attempt.

Settled current-key usage after the retry was $0.00232569, remaining $4.99767431 with the same $5 monthly cap and zero BYOK usage. The retry cost $0.00131952 by current-key delta. This total includes the initial questions and both isolated diagnostics and remains below the $0.25 verification target. The real HTTP response does not identify its downstream provider or request count; those remain unverified rather than inferred from configuration.

## Partial-search diagnosis

The parent authorized bounded diagnostics after inspecting the saved response and actual failure boundaries. A separate Logfire query attempt was rejected by automatic approval review before execution because process-environment token retrieval for that new purpose was not explicitly approved by the human; no Logfire query ran. The following probes instead used the owned app's normal secret bootstrap for its existing deployment grants, emitted no credential values, and did not mutate saved guides, configuration or services.

First, the actual full-text and dense adapters ran independently with the exact public question and captured allowed assessment, each with a 60-second deadline. They used read-only graph sessions and the existing local CPU embedder. Full-text succeeded with 3,584 candidates in 0.353 seconds; dense succeeded with 50 candidates in 0.439 seconds. These checks narrow current dependencies; they do not retrospectively prove which branch failed during the HTTP execution. The initial diagnostic harness had omitted the required dense candidate limit; its setup failed before either branch ran and was corrected to the production FusionConfig value.

Next, one isolated structural-only probe used the same question/assessment, a 60-second overall deadline and a transport ceiling of four actual OpenRouter HTTP requests. Existing output retries, provider policy and transport settings were preserved. It reproduced `structural`/`typed_selection`/`validation`, with a ValueError carrying the static message `Jev role selection failed`. Schema filtering passed; typed-selection normalization failed before composition, binding, CyVer/APOC or graph execution. Its backend usage recorded three requests, 14,337 input and 1,334 output tokens. It made **zero OpenRouter requests**.

Offline inspection ranked subtype-confidence abstention, TypeSafe response validation, and catalog mapping as explanations. One further expressly authorized selection-only probe capped actual TypeSafe HTTP requests at three and total duration at 60 seconds, with no OpenRouter or graph calls. All three requests returned HTTP 200. `jev-1.13.0` passed schema and parent-structure selection, then selected `LaborUnion` for one requested Organization subtype at **0.73**, below the unchanged **0.80** requirement. The other subtype scored 0.85. The exact error class was `SelectionAbstention`, with static code `uncertain_requested_category`; no answers were missing. It finished in 1.087 seconds with the same aggregate backend token usage as the structural probe.

This reproduces a question-specific conservative scope decision, not a demonstrated transport, authentication, corpus, APOC or embedding defect. Historical attribution remains limited because the original HTTP branch span was not queried. No threshold, prompt, validator or retry policy was relaxed to obtain a pass. The saved partial result honestly retains the two available articles.

## Second corrected-release HTTP question

The parent authorized exactly one additional submission with visitor B's existing cookie: `What should I read about Assembly Bill 1751 in California’s 2025-2026 legislative session?`. HTTPS returned 202 for guide `4899a688-a43e-4d3c-b148-1cfa340d6192`, attempt `f05c11ab-6606-4981-9cfe-9c7d2290fc60`. Its actual terminal outcome was `assessment_failed`, from `2026-10-13T02:43:39.486880Z` through `02:43:40.482856Z` (0.996 seconds), with no assessment or articles and no retrieval.

The hosting worker's scoped trace identified `QuestionAssessment.reading_order` as the literal string `"null"`, rejected with `literal_error`; its domain allows `relevance`, `publication_asc`, `publication_desc`, `event_asc` or `event_desc`. The terminal exception was `UnexpectedModelBehavior` with zero output retries. This is a different output defect from the corrected date-schema dialect. No value normalization, prompt change, validator change or extra retry was introduced to mask it. Actual downstream provider was not captured.

The owner reopened the failed guide and received identical terminal JSON. Visitor A received 404 for read/update/cancel. Read-only aggregate SQL recorded three guides, two owners, no unowned guides, four admissions and four attempts: two completed and two failed. The original partial guide and earlier failed attempt remain intact. Its settled cost was $0.00023416; total OpenRouter usage was $0.00255985, leaving $4.99744015 under the same $5 monthly cap. No additional HTTP submission followed this failure.

## Bounded candidate assessment

After current primary endpoint and catalog verification, the parent authorized one isolated assessment with `google/gemini-3.1-flash-lite`, exclusive ordered providers `google-ai-studio`, `google-vertex/global`. The process used normal app grants, the exact bill-focused question, captured coverage and the original guide's admission timestamp. It preserved the actual factory's Gemini profile, settings, prompts, validators and zero output retries; only model and provider configuration changed in the isolated process. The bounds were 60 seconds overall and four actual transport requests, with no retrieval, saved writes or persistent configuration changes.

The actual ChatSession assessment **passed** in 4.113 seconds including setup: `allowed`, typed None for both dates, and `reading_order: relevance`. One framework and actual HTTP request returned HTTP 200, response model `google/gemini-3.1-flash-lite`, observed provider `Google AI Studio`, 3,178 input and 89 output tokens. The existing SDK Google transformer was retained; `reasoning.effort: none` was accepted. Raw date values were JSON null. The raw reading-order getter returned None while the typed value was the relevance default; field presence was not captured, so this is not evidence that explicit null is accepted for the reading-order enum.

The response reported cost zero, and the immediate current-key snapshot remained $0.00255985 used/$4.99744015 remaining with the same $5 monthly cap. This was recorded as observed metadata, not an assumption that the priced route was free. A later settlement showed this request cost $0.000928 as Google BYOK usage, which is outside the current key limit.

## Gemini production HTTP journey

The parent changed only the app's existing model/provider configuration to `google/gemini-3.1-flash-lite` and `google-ai-studio,google-vertex/global`, plus trusted loopback proxy `127.0.0.1/32`. The hosting worker performed a controlled private reload, confirmed graceful Uvicorn/Neo4j shutdown, then checked readiness, all 383 files at the same `a74ca13...` revision, the unchanged image/corpus marker, and identical three-guide/four-attempt/four-admission baseline. The original B cookie reopened the failed bill guide unchanged.

One authorized HTTPS update retried that existing guide. The new attempt `e80f2fa2-e7cb-440c-a3e1-290a9f78f2a7` ran from `2026-10-13T02:52:35.160352Z` through `02:52:54.992173Z`, lasting **19.832 seconds**. It returned `completed`, an `allowed` assessment with typed None dates and relevance order, `partial: false`, `search_details.completion: completed`, and no disclosures. Its linked article was the expected [AB 1751 CalMatters report](https://calmatters.org/housing/2026/06/ab-1751-trades-carpenters-fight/), with publication metadata, nonempty reading direction and one Article Group. Bounded-selection details correctly reported one included article and omitted material; no verified highlights were available. This passes the real HTTP assessment, retrieval and saved-guidance path. Browser interactions remain outside verification.

Strict typed assertions passed, including unchanged question/guide/creation timestamp, a new completed attempt, expected citation, nonempty direction and included-article count. The subsequent owner GET exactly matched terminal JSON. Visitor A again received 404 for read/update/cancel. Read-only SQL confirmed three guides, two owners, no unowned guides, five admissions, and five attempts (three completed, two failed). All four prior attempt IDs and statuses remained stored, including both original failures and the partial reading attempt.

Post-journey peak memory was 1,798,045,696 bytes (about 1.675 GiB), against the same 5 GiB ceiling; swap and all OOM counters were zero. Transport settings stayed 60 seconds/two attempts/15-second wait cap. The runtime snapshot confirmed Gemini and the exclusive configured provider list. Actual downstream provider/request count of this HTTP journey was not captured; the isolated assessment observed Google AI Studio.

The current-key baseline before this retry revealed BYOK usage $0.000928 from the isolated Gemini assessment. The first post-journey snapshot showed $0.00221425, an additional **$0.00128625**, with OpenRouter-billed usage still $0.00255985. Its combined observed total was $0.00477410. A later explicitly authorized single read-only cap check showed BYOK usage **$0.006015** and combined observed usage **$0.00857485**, despite no further verifier paid requests. The earlier per-journey delta was therefore provisional; delayed settlement or other activity on the key cannot be distinguished by this aggregate metadata. Both observed totals remain below the $0.25 verification target.

The later check still reported a $5 monthly limit with `include_byok_in_limit: false`, so that limit does **not** bound Google BYOK charges. The verifier reported this immediately and submitted no further paid request. The parent has asked the user to enable BYOK inclusion while retaining the $5 monthly limit; public launch and further paid verification remain held. The verifier performed no repeat poll. Zero response-reported OpenRouter cost is not zero provider cost.

## Resource observations and remaining limits

Before the HTTP questions, cgroup peak memory was 2,287,812,608 bytes, about 2.131 GiB. After them it was 2,309,668,864 bytes, about 2.151 GiB. Swap current/peak and all OOM counters stayed zero. These readings include startup, CPU embedding probes and the two short assessments; they do **not** establish peak memory for a complete retrieval-and-guidance execution.

For the corrected container, pre-retry peak memory was 1,535,401,984 bytes (about 1.430 GiB), increasing to 1,629,179,904 bytes (about 1.517 GiB) after retrieval and reading guidance. The configured ceiling remained 5 GiB; swap current/peak and all OOM counters were zero. Effective transport settings remained 60 seconds, two attempts and a 15-second rate-limit wait cap.

The final private runtime trusts only loopback proxy `127.0.0.1/32`; actual anonymous public visitor-IP attribution remains a launch check. This verifier did not restart or kill any service; the hosting worker performed the parent's controlled replacements, after which existing cookie ownership and saved content were verified. A clean search with every expected branch handled is now verified through HTTP. Interruption recovery, actual owner cancellation, provider exhaustion and browser behavior remain unverified. The app remains owner-only pending publication and budget resolution. The user explicitly deferred off-server backup configuration, which is outside this phase.

Ignored HTTPS proof and diagnostic scripts are in `.scratch/hosted-http-verification-2026-10-12/`, indexed by `artifacts.json`. Cookie jars are 0600 and excluded from that index. Headers redact cookie values; owner authorization is injected by Bottle and never copied into proof.
