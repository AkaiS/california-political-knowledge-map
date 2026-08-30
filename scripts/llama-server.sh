#!/usr/bin/env bash
#
# Serve the coreference/extraction model through llama.cpp, with tool calling
# actually enforced.
#
# An OpenAI-compatible server may accept `tool_choice: "required"` without
# enforcing it, leaving pydantic-ai's structured output tool as a suggestion the
# model is free to answer in prose.  llama-server compiles the tool schema to a
# GBNF grammar and constrains decoding, so the tool call is the only output the
# sampler can reach.
#
# The GGUF has to be one llama.cpp can load.  Some model artifacts pack the
# vision tower into the same file, while llama.cpp wants the projector separate
# (see docs/adr/0019).
#
# Usage:
#   scripts/llama-server.sh
#   PORT=8081 CTX=65536 scripts/llama-server.sh
#   PARALLEL=1 scripts/llama-server.sh
#   MODEL_GGUF=/path/to/other.gguf scripts/llama-server.sh
#
set -euo pipefail

PORT="${PORT:-8080}"
CTX="${CTX:-65536}"
PARALLEL="${PARALLEL:-5}"
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
    echo "llama.cpp with the projector supplied separately." >&2
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

ctx_total=$(( CTX * PARALLEL ))

echo "gguf     $gguf"
echo "alias    $ALIAS"
echo "template ${template_args[1]:-<embedded in model>}"
echo "temp     $TEMP   ctx $CTX/slot x $PARALLEL slots = $ctx_total   port $PORT"
echo

# --temp 0 makes sampling deterministic even when a request omits temperature.
# The client sets temperature per request as well.
#
# --no-mmproj because nothing here sends an image, and loading the projector
# would only cost memory.
#
# `--ctx-size` is the TOTAL KV pool, which llama.cpp divides evenly among the
# slots: n_ctx_slot = n_ctx / n_parallel.  So CTX here means per-slot context
# and the total is computed from it -- otherwise raising PARALLEL would quietly
# shrink every slot's window instead of adding capacity.
#
# Five slots because decode at batch size 1 is memory-bandwidth-bound: the GPU
# spends its time streaming weights, not computing, so batching several
# sequences reads those weights once and applies them to all of them.  Measured
# on this machine that is ~79 t/s aggregate across five slots against ~40 t/s
# on one -- roughly 2x, not 5x, because gemma-4-26B is 26B-A4B and concurrent
# sequences route to different experts, which is exactly the weight sharing
# batching depends on.  Set PARALLEL=1 to get the whole pool back on one slot.
#
# The template array is expanded through `${x[@]+...}` because bash 3.2, which
# is what /bin/bash is on macOS, treats an empty array as unset under `set -u`.
exec llama-server \
    --model "$gguf" \
    --alias "$ALIAS" \
    ${template_args[@]+"${template_args[@]}"} \
    --jinja \
    --no-mmproj \
    --ctx-size "$ctx_total" \
    --parallel "$PARALLEL" \
    --temp "$TEMP" \
    --top-k 1 \
    --n-gpu-layers 999 \
    --host 127.0.0.1 \
    --port "$PORT"
