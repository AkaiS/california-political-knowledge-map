#!/usr/bin/env bash
#
# Serve the coreference/extraction model through llama.cpp, with tool calling
# actually enforced.
#
# Ollama accepts `tool_choice: "required"` and ignores it, so pydantic-ai's
# structured output tool is a suggestion the model is free to answer in prose --
# which is what it did.  llama-server compiles the tool schema to a GBNF grammar
# and constrains decoding, so the tool call is the only output the sampler can
# reach.
#
# The GGUF has to be one llama.cpp can load, which the blobs under
# ~/.ollama/models are not: Ollama packs the vision tower into the same file,
# and llama.cpp wants the projector separate (see docs/adr/0019).
#
# Usage:
#   scripts/llama-server.sh
#   PORT=8081 CTX=65536 scripts/llama-server.sh
#   MODEL_GGUF=/path/to/other.gguf scripts/llama-server.sh
#
set -euo pipefail

PORT="${PORT:-8080}"
CTX="${CTX:-32768}"
TEMP="${TEMP:-0}"
ALIAS="${ALIAS:-gemma4:26b}"

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
model_dir="${LLAMA_MODEL_DIR:-$HOME/Library/Caches/llama.cpp}"
gguf="${MODEL_GGUF:-$model_dir/gemma-4-26B_q4_0-it.gguf}"

command -v llama-server >/dev/null || {
    echo "llama-server not found. Install it with: brew install llama.cpp" >&2
    exit 1
}

if [[ ! -f "$gguf" ]]; then
    cat >&2 <<EOF
Model not found: $gguf

Download it (14.44 GB), or point MODEL_GGUF at your own copy:

  mkdir -p "$model_dir"
  curl -L -C - -o "$gguf" \\
    https://huggingface.co/google/gemma-4-26B-A4B-it-qat-q4_0-gguf/resolve/main/gemma-4-26B_q4_0-it.gguf
EOF
    exit 1
fi

# Preflight, because both failures this catches are otherwise obscure: a packed
# projector aborts the load with a tensor count mismatch that never says
# "vision", and a missing chat template loads fine and then silently declares no
# tools, which is the bug this whole move exists to fix.
eval "$(python3 "$repo_root/scripts/gguf_inspect.py" "$gguf")"

if [[ "$vision_tensors" != "0" ]]; then
    echo "$gguf packs $vision_tensors vision/projector tensors." >&2
    echo "llama.cpp needs the projector in a separate --mmproj file and will" >&2
    echo "refuse this one with 'wrong number of tensors'. Use a GGUF built for" >&2
    echo "llama.cpp rather than an Ollama blob." >&2
    exit 1
fi

template_args=()
if [[ -n "${TEMPLATE:-}" ]]; then
    template_args=(--chat-template-file "$TEMPLATE")
elif [[ "$chat_template" == "no" ]]; then
    fallback="$repo_root/chat-templates/gemma-4.jinja"
    echo "note: $gguf carries no chat template; using $fallback" >&2
    template_args=(--chat-template-file "$fallback")
fi

echo "gguf     $gguf"
echo "alias    $ALIAS"
echo "template ${template_args[1]:-<embedded in model>}"
echo "temp     $TEMP   ctx $CTX   port $PORT"
echo

# --temp 0 replaces the temperature 1 / top_p 0.95 that ship in the Ollama
# Modelfile.  The client sets temperature per request as well; this makes a
# request that omits it deterministic too.
#
# --no-mmproj because nothing here sends an image, and loading the projector
# would only cost memory.
#
# `--parallel 1` because the default of 4 gives every slot its own full
# `--ctx-size` of KV cache for a pipeline that only ever has one client, and
# because concurrent slots silently halve decode throughput when a stray
# second process shows up.
#
# The template array is expanded through `${x[@]+...}` because bash 3.2, which
# is what /bin/bash is on macOS, treats an empty array as unset under `set -u`.
exec llama-server \
    --model "$gguf" \
    --alias "$ALIAS" \
    ${template_args[@]+"${template_args[@]}"} \
    --jinja \
    --no-mmproj \
    --ctx-size "$CTX" \
    --parallel 1 \
    --temp "$TEMP" \
    --top-k 1 \
    --n-gpu-layers 999 \
    --host 127.0.0.1 \
    --port "$PORT"
