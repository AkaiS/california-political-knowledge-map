#!/usr/bin/env bash
#
# Serve the embedding model through llama.cpp, alongside the chat server.
#
# `llama-server` serves one model per process, so this is a second process on a
# second port rather than a flag on `scripts/llama-server.sh`.  Nothing here
# needs a grammar or a chat template: both chat and embedding stay on the local
# llama.cpp runtime.
#
# The GGUF has to be llama.cpp's own conversion.  A model artifact that declares
# `general.architecture = gemma3` is loaded with the text-model loader, which
# has no slot for EmbeddingGemma's two dense projection tensors and aborts with
# `wrong number of tensors; expected 316, got 314`.  See `docs/adr/0019`.
#
# Usage:
#   scripts/llama-embed.sh
#   PORT=8082 scripts/llama-embed.sh
#   EMBED_GGUF=/path/to/other.gguf scripts/llama-embed.sh
#
set -euo pipefail

PORT="${PORT:-8081}"
ALIAS="${ALIAS:-embeddinggemma}"

model_dir="${LLAMA_MODEL_DIR:-$HOME/Library/Caches/llama.cpp}"
gguf="${EMBED_GGUF:-$model_dir/embeddinggemma-300M-Q8_0.gguf}"

command -v llama-server >/dev/null || {
    echo "llama-server not found. Install it with: brew install llama.cpp" >&2
    exit 1
}

if [[ ! -f "$gguf" ]]; then
    cat >&2 <<MSG
Model not found: $gguf

Download it (318 MB), or point EMBED_GGUF at your own copy:

  mkdir -p "$model_dir"
  curl -L -C - -o "$gguf" \\
    https://huggingface.co/ggml-org/embeddinggemma-300M-GGUF/resolve/main/embeddinggemma-300M-Q8_0.gguf

It must be that repository.  Every third-party conversion checked -- unsloth
BF16 and F32, second-state f16 -- ships 314 tensors and silently omits
\`dense_2\`/\`dense_3\`, the Matryoshka projection head.  Such a file loads
without complaint and returns embeddings from the wrong space.
MSG
    exit 1
fi

echo "gguf     $gguf"
echo "alias    $ALIAS   port $PORT"
echo

# --ctx-size 2048 is the model's own trained context.  A chunk is 512
# characters, so nothing comes close to it.
#
# --ubatch-size has to reach --ctx-size: the model is non-causal
# (`attention.causal = false`), so llama.cpp cannot split a sequence
# across micro-batches and refuses a request longer than one.
#
# --pooling is deliberately not passed.  The GGUF declares mean pooling
# (`gemma-embedding.pooling_type = 1`) and llama.cpp honours that; overriding it
# would silently change every vector in Neo4j.
exec llama-server \
    --model "$gguf" \
    --alias "$ALIAS" \
    --embeddings \
    --ctx-size 2048 \
    --batch-size 2048 \
    --ubatch-size 2048 \
    --parallel 1 \
    --n-gpu-layers 999 \
    --host 127.0.0.1 \
    --port "$PORT"
