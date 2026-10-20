# llama.cpp serves chat so tool calls are enforced

Every local chat agent that returns structured output talks to `llama-server`, started from
`scripts/llama-server.sh`, at `LLAMA_CPP_BASE_URL`. The original move left the
embedding stage on Ollama temporarily; the current runtime keeps embeddings
local too, on their own llama.cpp server. The chat weights are served from
`gemma-4-26B_q4_0-it.gguf` from
`google/gemma-4-26B-A4B-it-qat-q4_0-gguf`, cached outside the repository.

This record covers only the local Model Deployment. OpenRouter is a separate chat Model Deployment
and uses its provider's structured-output behavior; the local llama.cpp enforcement described here
does not apply to it.

> **Legacy:** the paragraph above no longer describes OpenRouter structured output. Superseded by
> [ADR 0026](0026-openrouter-chat-uses-strict-native-structured-output.md).

pydantic-ai's default output mode synthesises a `final_result` tool and sends
`tool_choice: "required"`. On llama.cpp that is binding — the tool's JSON schema
is compiled to a GBNF grammar and decoding is constrained to it, so the tool call
is the only output the sampler can reach. That is the whole reason for the move.

## Why now

Coreference Resolution produced zero Mention Spans across an entire Source
Article, four annotator attempts in a row, with an empty audit trail. The chain
was traced end to end rather than inferred:

pydantic-ai built the output tool correctly, and it arrived at Ollama intact —
a transport capture showed `tools: ['final_result']` and `tool_choice: "required"`
on the wire. Ollama accepted `tool_choice: "required"` and ignored it; a direct
`curl` with no framework involved reproduced that. The model then answered in
prose. The isolating comparison: identical model, identical question, identical
`{city: str}` parameters — declared as `get_weather` / "Get current weather for a
city" it called the tool; declared as `final_result` / "The final response which
ends this conversation" it replied in text. In tool mode pydantic-ai discards
text, so four attempts produced four discarded replies and a DLQ record reading
`mention_spans: 0`.

The prose it returned was correct coreference. The model was never the problem,
and switching models would not have helped: `8k-gemma-e4b-extraction` fails the
same tool-call test.

The missing piece is the chat template. No `gemma4` GGUF in the local Ollama
store carries a `tokenizer.chat_template` key — Ollama renders prompts with its
own Go templates and drops the Jinja one. The canonical Gemma 4 template, now
committed at `chat-templates/gemma-4.jinja`, declares `supports_tools`,
`supports_tool_calls`, and `supports_parallel_tool_calls`. Gemma 4 could call
tools the entire time; the server was not telling it how.

## Considered options

Prompting for JSON and parsing the reply — pydantic-ai's `PromptedOutput` — was
rejected. It works against a model that ignores tools and breaks against one that
honours them, which makes the correct output mode a property of the deployment
rather than of the task, and makes a stronger model a regression.

`NativeOutput` over `response_format: json_schema` was rejected as the primary
mode. llama.cpp enforces it with the same grammar machinery, so it is a real
fallback, but it gives up the tool-call message shape that the Coreference
Critic rounds and the pydantic-ai retry path are already written against.

Staying on Ollama and waiting for `tool_choice` to be honoured was rejected. The
behaviour is not a bug we can date, and the failure mode it produces is silent:
a discarded reply is indistinguishable from a model that had nothing to say.

Serving the Ollama blob directly was the intended plan and does not work.
llama.cpp requires the vision projector in a separate `--mmproj` file; Ollama
packs it into the model file. The 26B blob holds 658 text tensors and 356
vision/projector tensors, so llama.cpp builds the text model, counts 658 against
the header's 1014, and aborts with `wrong number of tensors` — an error that
never says "vision". There is no flag that splits a packed file.

Rewriting the blob locally into a text-only GGUF was rejected. It avoids a
download and preserves the exact weights, but it means hand-rolling a GGUF
writer to produce a non-standard artifact, and the official build is
quantization-aware trained rather than quantized after the fact.

## Consequences

`get_chat_model` returns an `OpenAIChatModel` on an `OpenAIProvider` for the
local llama.cpp chat server. `resolve_embedding_base_url` names the separate
local embedding `llama-server` on port 8081 rather than Ollama on 11434 — see
"Embeddings remain local" below.

Temperature is 0 by default, set on the client via `LLM_TEMPERATURE` and again by
`scripts/llama-server.sh --temp 0`. Extraction and coreference transcribe a fixed
Source Article; sampling breadth was never wanted, and the Ollama Modelfile's
`temperature: 1, top_p: 0.95` was in force until now.

The model profile declares `openai_supports_strict_tool_definition=False`:
llama.cpp constrains with a grammar and has no OpenAI-style strict mode, so
asking for one is rejected.

Running the pipeline now requires a second process, and the chat weights are a
separate 14 GB artifact that Ollama no longer manages. `scripts/llama-server.sh`
inspects the GGUF header before launching and refuses a packed-projector file by
name, because that failure is otherwise diagnosed from a tensor count.

The QAT build replaces a post-hoc `Q4_K_M` quantization with one trained at 4
bits. Output will differ from every previous run; nothing here has an evaluation
baseline to invalidate.

The chat template ships inside that GGUF, byte-identical to
`chat-templates/gemma-4.jinja`, so the committed copy is a fallback for GGUFs
that lack one rather than a required input.

The obsolete `OLLAMA_MODEL_*` chat names were removed from runtime
configuration, `.env.example`, tests, and active operator guidance. They are
named here only as historical context for that migration and were replaced by
`LLAMA_CPP_MODEL`; the configured name still identifies the GGUF alias served
by `llama-server`.

## What enforcement actually required

The title of this record is the goal, not a description of what worked. Pointing
the agents at `llama-server` with `tool_choice: "required"` was necessary and not
sufficient; two further findings were needed before a coreference run completed
at all. Both were silent failures — no error, no warning, just a run that never
finished.

### Reasoning had to be turned off explicitly

Gemma 4's chat template defaults `enable_thinking` to false, but `llama-server`
runs `--reasoning auto`, which turns it back on. pydantic-ai sends no
`max_tokens`, so nothing bounds the reasoning. The same annotator request:

| | thinking on | thinking off |
|---|---|---|
| `finish_reason` | `length` | `tool_calls` |
| reasoning characters | 6,181 | 0 |
| wall clock | never finished | 29 s |

The flag is read by the template rather than the sampler, so it travels in the
request body as `chat_template_kwargs`, set in the model factory. Putting it in
the launch script instead would leave it out of the code that depends on it.

### Structured output does not go through a tool call

Gemma 4's tool-call syntax does not match the `peg-gemma4` parser in
`llama-server`. The model answers correctly and completely, closes with a literal
`<tool_call|>` — which is not a real special token, so it does not stop decoding
— and then repeats the entire answer verbatim until the context is exhausted.
The parser finds no tool call and returns the text as ordinary content;
pydantic-ai sees no result and retries, three more times. That is the whole of
the fifteen-minute run: four unbounded generations, each discarded.

A `$ref` in the schema fails the same way and compounds it. `llama-server` does
not reject an unresolved reference — it drops the grammar constraint and lets the
model generate freely. With `$ref`, the annotator produced 4,000 unconstrained
tokens, no tool call, and invented the fields `start`, `end`, and `text`, which
`MentionSpan` does not have. With the definitions inlined, the identical request
returned 30 valid spans in 18 s.

Both are fixed in the local Model Deployment's model profile, which is the one
place every local agent shares:
`default_structured_output_mode="native"` routes structured output through
`response_format: json_schema`, which compiles a real GBNF grammar, and
`InlineDefsJsonSchemaTransformer` keeps `$ref` off the wire. The transformer sits
in the last position of the `merge_profile` call because merging is last-wins and
the upstream Google profile supplies a transformer that preserves `$ref`.

Measured end to end on one 25-sentence article, before and after:

| | tool output, `$ref` | native output, inlined |
|---|---|---|
| annotator | 4,000 tokens, no result | 56 spans, 49 located |
| critic | ran to the 32k context | 49 verdicts, 49 accepted |
| correction rounds | exhausted, then failed | 0 |
| wall clock | ~15 min, no result | **92 s, resolved** |

Enforcement is therefore grammar-constrained JSON, not a constrained tool call.
That is strictly stronger than what Ollama provided — Ollama accepted
`tool_choice: "required"` and ignored it — but it is a different mechanism than
this record's title implies, and `supports_json_schema_output` is what carries it.

## Amendment: inline ontology dictionary-key constraints

On October 1, 2026, structural retrieval exposed a missing traversal in the
installed Pydantic AI 2.31.1 schema transformer. `OntologySelection` generates
a `propertyNames` reference for its `SemanticLabel` dictionary keys. The
transformer removes `$defs` without walking that keyword, leaving a dangling
reference. The current local server rejects this request with HTTP 400 before
generation starts.

`OntologySelection.filter_properties` now uses Pydantic's `json_schema_extra`
to emit the key enum inline. `TypeAdapter(SemanticLabel)` supplies that enum
from the existing type. Runtime validation still rejects unknown labels and
invalid filter properties. This uses the library's schema customization without
adding a custom walker or changing the structured-output transport. The model
factory regression test checks the actual wire schema and typed-key validation.

The production ontology-filter replay now receives HTTP 200. Its later
correction exhaustion is a model-output validation failure, separate from
request-schema conversion. The annotation can be removed when the upstream
inliner handles `propertyNames`, provided the wire-schema regression still
passes.

## Embeddings remain local

An embedding call has no tool use to enforce, so the argument above does not
reach it. The later embedding migration kept it local so the pipeline depends
on Ollama for neither chat nor embeddings.

`llama-server` serves one model per process, so this is a second process on a
second port — `scripts/llama-embed.sh`, port 8081, `LLAMA_CPP_EMBEDDING_BASE_URL`
— rather than a flag on the chat server.

### The Ollama blob does not load here either, for a different reason

Reusing the blob under `~/.ollama/models` was tried first and failed with `wrong
number of tensors; expected 316, got 314`. The cause is not the packed vision
tower that stopped the 26B: EmbeddingGemma has none (`gguf_inspect.py` reports
`vision_tensors=0`). Ollama's blob declares `general.architecture = gemma3`, so
llama.cpp loads it with the text-model loader, which builds 314 tensors and has
no slot for `dense.0.weight` `[768, 3072]` and `dense.1.weight` `[3072, 768]` —
EmbeddingGemma's Matryoshka projection head. llama.cpp implements those under a
dedicated `gemma-embedding` architecture, which the Ollama conversion does not
declare.

### Only the official conversion is complete

`ggml-org/embeddinggemma-300M-GGUF` is the one to use, and the launcher says so.
Every third-party conversion checked — unsloth BF16, unsloth F32, second-state
f16 — declares `gemma-embedding` but ships **314** tensors, silently omitting
`dense_2`/`dense_3`. Such a file loads without a word of complaint and returns
768-dimension vectors from the wrong space, so the adapter's dimension check
still passes. This is worth more than the precision: the official file is Q8_0
rather than the bf16 Ollama served, and a near-lossless quantization of the right
model beats an exact copy of a truncated one.

Vectors are therefore close to but not bit-identical with what Neo4j already
holds. If that matters, re-embed rather than assume.

### Serving flags

`--pooling` is deliberately not passed. The GGUF declares
`gemma-embedding.pooling_type = 1` (mean) and llama.cpp honours the model's own
declaration, as Ollama did; setting it would silently change every vector.

`--ubatch-size` has to reach `--ctx-size`. The model is non-causal, so llama.cpp
cannot split one sequence across micro-batches and rejects any request longer
than a single one. The context is the model's own 2048, which is what the Ollama
Modelfile set; a chunk is 512 characters and comes nowhere near it.

`EMBEDDING_MODEL` is the active embedding name. `OLLAMA_EMBEDDING_MODEL` remains
only as a compatibility fallback for an existing `.env`; it is not a chat
Model Deployment name and cannot select a chat deployment.
