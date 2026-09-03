Project Overview: CA Political Knowledge Map — synchronous Story Pipeline that processes a SourceArticle through coreference resolution -> chunking -> embedding -> entity extraction -> persistence (`src/knowledge_map/core/pipeline.py:120`).
Dual store: SQLite document store (`document_store.db`, `src/knowledge_map/adapters/sqlite_db.py:15`) plus Neo4j graph.
Two chat Model Deployments: local llama.cpp-served GGUF and OpenRouter upstream model with local embeddings (see `docs/model-deployments.md`).

## Project planning

The local work tracker starts at [`work/README.md`](work/README.md). Product
direction lives in [`work/roadmap.md`](work/roadmap.md), while unshaped ideas,
defects, and questions are captured in [`work/inbox.md`](work/inbox.md).

## Setting up a Git worktree

After creating and entering a new worktree, run:

```bash
./scripts/setup-worktree.sh
```

The script finds the primary worktree automatically, copies local configuration
that should remain independent (`.env`, `.agents`, and Logfire credentials),
symlinks the shared `document_store.db`, creates fresh scratch directories, and
runs `uv sync --frozen`. It never overwrites files already present in the new
worktree and deliberately excludes `.venv`, caches, logs, and dead-letter queue
data.

Use `--dry-run` to preview the setup, `--source PATH` to transfer local state
from a different worktree, or `--skip-sync` when dependencies are already set
up.

## Model deployments

Operational guidance for choosing local llama.cpp or OpenRouter chat, configuring
providers and BYOK, and reading Evaluation Run provenance is in
[`docs/model-deployments.md`](docs/model-deployments.md).
