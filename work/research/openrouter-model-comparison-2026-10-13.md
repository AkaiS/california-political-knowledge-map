# OpenRouter alternatives to deployed Gemma 4 26B

Checked October 13, 2026. This is a research snapshot. No inference calls, configuration changes, or deployment changes were made.

Deployment evidence was read from commit `2e59371097c1071f463401a18d3334843e0d67a2` on `codex/cloud-in-a-bottle-deployment`. Its `docs/cloud-deployment.md` and `docs/cloud-credentials.md` are not yet on `main`; read them with `git show COMMIT:PATH` using that revision and path.

## Recommendation

Evaluate DeepSeek V4 Flash 0731 and Ling 3.0 Flash VL through DeepInfra, plus Solar Mini 4 through Upstage. All currently cost less per input and output token than the deployed model, advertise the schema and tool controls the application needs, and score higher on broad independent evaluations. The DeepInfra routes have no listed promotion. Solar's current price includes a 50% discount. These are candidates for a controlled application evaluation, not established improvements in Source Guide quality.

Haiku 5.5 and GPT-6 Luna are useful quality comparisons at a modestly higher token price. Their request compatibility needs more work. In particular, Haiku's current endpoints do not advertise temperature or required/function tool choice. A model ID change alone would not make it a safe replacement.

## The deployed baseline

The user confirmed the deployment uses paid Gemma. Repository deployment evidence identifies `google/gemma-4-26b-a4b-it`, exclusively `deepinfra/fp8`, at $0.07 per million input tokens and $0.34 per million output tokens. The local free-model settings do not describe this deployment. The selected endpoint has 262,144 context tokens, native structured output, and required/function tool choice. Sources: `docs/cloud-deployment.md` at the evidence revision, `docs/cloud-credentials.md` at the evidence revision, and [OpenRouter endpoint API](https://openrouter.ai/api/v1/models/google/gemma-4-26b-a4b-it/endpoints).

OpenRouter's catalog currently gives $0.09/$0.30 for the paid model, while the public page lists a $0.042/$0.22 provider floor. Neither is the deployed rate. Compare actual eligible endpoints, not the catalog headline. The [Gemma model page](https://openrouter.ai/google/gemma-4-26b-a4b-it) reports Artificial Analysis Intelligence Index scores of 13.1 without reasoning and 16.7 with reasoning. The application currently disables thinking, so 13.1 is the closer reference.

## Shortlist

Prices are USD per million uncached text tokens. Context is the selected route's limit when verified, otherwise the model catalog limit. Quality scores below are OpenRouter's reproduction of Artificial Analysis results, with reasoning settings shown. A higher index does not prove better extraction, citations, abstention, or California politics answers.

| Model and exact OpenRouter ID | Route or price basis | Input | Output | Context tokens | Quality evidence and qualification |
| --- | --- | ---: | ---: | ---: | --- |
| Deployed Gemma 4 26B, `google/gemma-4-26b-a4b-it` | DeepInfra FP8 | $0.07 | $0.34 | 262,144 | AA 13.1 thinking off; 16.7 reasoning |
| [Ling 3.0 Flash VL](https://openrouter.ai/inclusionai/ling-3.0-flash-vl), `inclusionai/ling-3.0-flash-vl` | DeepInfra FP16, no listed discount | $0.06 | $0.18 | 131,072 | AA 24.6 reasoning; cheaper in both directions |
| [Solar Mini 4](https://openrouter.ai/upstage/solar-mini4), `upstage/solar-mini4` | Upstage, 50% promotion | $0.05 | $0.20 | 524,288 | AA 24.1 reasoning; current price cheaper in both directions |
| [DeepSeek V4 Flash 0731](https://openrouter.ai/deepseek/deepseek-v4-flash-0731), `deepseek/deepseek-v4-flash-0731` | DeepInfra FP8 | $0.06 | $0.18 | 1,048,576 | AA 34.3 max reasoning; cheaper in both directions |
| [Qwen3.7 Flash](https://openrouter.ai/qwen/qwen3.7-flash), `qwen/qwen3.7-flash` | Alibaba, prompts below 32,000 tokens | $0.03 | $0.13 | 1,000,000 | Cost candidate; comparable AA evidence not found; JSON output lacks schema enforcement |
| [Ling 3.1 Flash](https://openrouter.ai/inclusionai/ling-3.1-flash), `inclusionai/ling-3.1-flash` | NovitaAI, 75% promotion | $0.075 | $0.225 | 262,144 | AA 41.1; lacks advertised native schema output; lower priority |
| [Claude Haiku 5.5](https://openrouter.ai/anthropic/claude-haiku-5.5), `anthropic/claude-haiku-5.5` | Standard route, prompts below 100,000 tokens | $0.10 | $0.50 | 1,000,000 | AA 43.4 at max effort; compatibility changes required |
| [GPT-6 Luna](https://openrouter.ai/openai/gpt-6-luna), `openai/gpt-6-luna` | Standard route, prompts below 272,000 tokens | $0.10 | $0.50 | 1,050,000 | AA 38.1 max; 18.5 thinking off; catalog does not advertise temperature |
| [Gemma 4 31B](https://openrouter.ai/google/gemma-4-31b-it), `google/gemma-4-31b-it` | DeepInfra Turbo | $0.09 | $0.34 | 262,144 | AA 13.9 thinking off; 14.7 reasoning. Google reports stronger family benchmarks, but not a broad independent win |

Exact route compatibility and prices for the first candidates came from the [Ling endpoint API](https://openrouter.ai/api/v1/models/inclusionai/ling-3.0-flash-vl/endpoints), [Solar endpoint API](https://openrouter.ai/api/v1/models/upstage/solar-mini4/endpoints), [DeepSeek 0731 endpoint API](https://openrouter.ai/api/v1/models/deepseek/deepseek-v4-flash-0731/endpoints), and [Haiku endpoint API](https://openrouter.ai/api/v1/models/anthropic/claude-haiku-5.5/endpoints). Model-wide capabilities and pricing tiers came from the [OpenRouter catalog](https://openrouter.ai/api/v1/models). They do not guarantee each provider supports those controls.

### Prices that need care

- Ling 3.0 VL's headline $0.021/$0.0616 is a 72% NovitaAI promotion. That endpoint does not advertise native schema enforcement. DeepInfra's $0.06/$0.18 is the stronger candidate for the application's strict output needs. Novita's undiscounted price is $0.075/$0.22. [Ling model page](https://openrouter.ai/inclusionai/ling-3.0-flash-vl).
- Solar's undiscounted $0.10/$0.40 is more expensive than deployed Gemma in both directions. No promotion end date was established. [Solar model page](https://openrouter.ai/upstage/solar-mini4).
- Qwen3.7 Flash increases to $0.10/$0.40 at 32,000 prompt tokens and $0.20/$0.80 at 256,000. The cheapest tier should not be applied to full article reading or long conversation histories without measuring their length. [Catalog](https://openrouter.ai/api/v1/models).
- Haiku increases to $0.50/$2.50 above 100,000 prompt tokens. Its first-party launch confirms both tiers. [Anthropic launch](https://www.anthropic.com/claude-haiku-5-5).
- GPT-6 Luna increases to $0.20/$0.75 at 272,000 prompt tokens. Cache reads and writes use separate prices. [Catalog](https://openrouter.ai/api/v1/models).
- `deepseek/deepseek-v4-flash` identifies 0423. The newer `deepseek/deepseek-v4-flash-0731` is a separate SKU. Its DeepInfra FP8 endpoint confirms $0.06/$0.18, schema support, temperature, and required/function tool choice. Do not attach its benchmark score to the older endpoint. [0731 model page](https://openrouter.ai/deepseek/deepseek-v4-flash-0731), [0731 endpoint API](https://openrouter.ai/api/v1/models/deepseek/deepseek-v4-flash-0731/endpoints).

For a hypothetical 10,000-input, 1,000-output-token request, uncached cost is $0.00104 on deployed Gemma, $0.00078 on either DeepInfra candidate, and $0.00070 on discounted Solar. Those imply 25% and 33% savings before retries or reasoning tokens. The last documented deployed Source Guide cost $0.00135362. At that scale, valid answers and successful tool use matter more than saving fractions of a cent. Source: `docs/cloud-deployment.md` at the evidence revision.

## What the quality evidence actually establishes

Artificial Analysis owns the benchmark methodology. Its current pages use Intelligence Index v4.3.2, covering knowledge work, agent workflows, long context, coding, and other tasks. Its [Ling 3.0 VL page](https://artificialanalysis.ai/models/ling-3-0-flash-vl) rounds the current score to 25 and identifies the reasoning variant. The [first-party Ling card](https://huggingface.co/inclusionAI/Ling-3.0-flash-VL) reports 42 on the earlier v4.1.1 index. Those numbers cannot be compared as if the index had stayed unchanged.

The primary [Solar Mini 4 analysis](https://artificialanalysis.ai/models/solar-mini4) rounds its score to 24 and identifies the reasoning variant. It also reports 370 million output tokens over the benchmark suite, versus a comparison median of 95 million. That verbosity makes total cost and time important even while the unit prices look favorable. The primary [Haiku 5.5 analysis](https://artificialanalysis.ai/models/claude-haiku-5-5) and [GPT-6 Luna analysis](https://artificialanalysis.ai/models/gpt-6-luna) identify max-effort evaluations. They should not be treated as predictions of thinking-off behavior.

The current same-benchmark AA-LCR scores reproduced on OpenRouter are 65.7 for reasoning Gemma 26B, 78.3 for Ling 3.0 VL, and 83.3 for Solar Mini 4. These support investigating article reading and Source Guide generation. They do not evaluate source selection or faithfulness under this application's prompts. With thinking off, Gemma's AA-LCR is 42.3. [Gemma](https://openrouter.ai/google/gemma-4-26b-a4b-it), [Ling](https://openrouter.ai/inclusionai/ling-3.0-flash-vl), [Solar](https://openrouter.ai/upstage/solar-mini4).

Google's own Gemma family comparison gives 31B versus 26B MMLU Pro of 85.2% versus 82.6%, Tau2 three-domain average of 76.9% versus 68.2%, and MRCR v2 128K of 66.4% versus 44.1%. That is useful direct family evidence. Independent AA scores show only a small off-mode advantage and a lower aggregate reasoning index for 31B. [Google model card](https://ai.google.dev/gemma/docs/core/model_card_4), [31B independent results reproduced by OpenRouter](https://openrouter.ai/google/gemma-4-31b-it).

Anthropic's Haiku 5.5 launch compares it directly with GPT-6 Luna on the same knowledge-work tasks. GDPval-AA v2.1 Elo is 1620 versus 1437, and AA-Briefcase v1.1 Elo is 1578 versus 1336. This is first-party reported evidence, not an application comparison. The launch also documents adjustable effort. [Anthropic launch](https://www.anthropic.com/claude-haiku-5-5).

## Quality and speed are separate decisions

The public model pages show provider-specific recent P50 measurements. The following snapshot was refreshed on October 13, 2026 for the five models in the chat comparison. TPS means generated tokens per second. The latency column is OpenRouter's reported latency, separate from generation throughput.

| Model | Provider row | Input / million | Output / million | P50 TPS | Reported P50 latency |
| --- | --- | ---: | ---: | ---: | ---: |
| [Deployed Gemma 4 26B](https://openrouter.ai/google/gemma-4-26b-a4b-it) | DeepInfra FP8 | $0.07 | $0.34 | 42 | 0.41 s |
| [Ling 3.0 Flash VL](https://openrouter.ai/inclusionai/ling-3.0-flash-vl) | DeepInfra FP16 | $0.06 | $0.18 | 35 | 1.22 s |
| [DeepSeek V4 Flash 0731](https://openrouter.ai/deepseek/deepseek-v4-flash-0731) | DeepInfra FP8 | $0.06 | $0.18 | 17 | 2.57 s |
| [Solar Mini 4](https://openrouter.ai/upstage/solar-mini4) | Faster displayed Upstage row, 50% promotion | $0.05 | $0.20 | 57 | 2.13 s |
| [Claude Haiku 5.5](https://openrouter.ai/anthropic/claude-haiku-5.5) | Standard Anthropic row | $0.10 | $0.50 | 145 | 1.98 s |

Solar's other displayed Upstage row reports 41 TPS and 2.46-second latency at the same token price. The public page labels both rows Upstage, so the faster observation is not a guarantee for every Upstage route. These measurements fluctuate and do not establish an application speed win. Reasoning tokens, output length, retries, tool rounds, and load affect total Source Guide time. Haiku has the highest generation throughput among these selected provider rows; deployed Gemma has the lowest reported initial latency.

Haiku's max-effort score may require more reasoning than the application needs. In the original research snapshot, GPT-6 Luna's standard OpenAI row showed 2.92 seconds and 67 tokens per second; that row was not refreshed for the five-model TPS follow-up. Their best displayed providers include different prices or routing eligibility. Use the selected endpoint's numbers, not a model-wide best speed attached to its cheapest rate. [Haiku](https://openrouter.ai/anthropic/claude-haiku-5.5), [Luna](https://openrouter.ai/openai/gpt-6-luna).

## Application checks before a switch

The deployment uses exclusive provider routing, and the application requires supported request parameters. A non-Gemma replacement also changes the assessment output mode unless the current Gemma-specific native output branch is reviewed. Compare the complete request behavior: native Question Assessment schema, Source Guide tools, required tool choice, temperature, thinking settings, and provider fallback policy. OpenRouter's [provider routing documentation](https://openrouter.ai/docs/guides/routing/provider-selection) explains `require_parameters` and provider selection.

For a controlled comparison, retain the deployed model as baseline and run the same Evaluation Cases against DeepSeek 0731 DeepInfra, Ling DeepInfra, and Solar Upstage. Record successful end-to-end cost including retries and reasoning, total latency, schema failures, unsupported claims, source coverage, and abstention. Also inspect empty or repeated tool calls. A lower price per token can still cost more per accepted Source Guide.

Free Gemma 31B remains a possible development trial at $0/$0. It is a separate route with its own constraints and should not replace the paid deployment based on price alone. [Free model page](https://openrouter.ai/google/gemma-4-31b-it:free).
