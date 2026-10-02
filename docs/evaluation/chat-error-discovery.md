# Discover Chat Session errors

Use this reviewer to discover failures from free-text observations. The existing
[answer reviewer](chat-answer-review.md) remains available for case verdicts.
Discovery begins without quality labels or a predefined taxonomy.

Prepare the 100-case synthetic run:

```bash
uv run python scripts/prepare_chat_discovery.py \
  evals/reports/chat/20261001T000642Z-e17ffc5-local-gemma4-26b-1499ceec2201.json \
  --data-dir work/initiatives/model-evaluation/error_discovery_data/chat-synthetic
```

Start the reviewer:

```bash
uv run python scripts/error_discovery_chat.py \
  --data-dir work/initiatives/model-evaluation/error_discovery_data/chat-synthetic \
  --port 8766
```

Visit <http://127.0.0.1:8766/>. Select text within a content block and write an
observation. Enter saves; Shift+Enter adds a line. Notes appear beside their
highlighted passages. Add case note anchors a general observation to the
original question. Notes save to `annotations.json` and have a browser-local
backup for pending file saves. Failed saves remain queued and can be retried.
Edits to an existing note remain drafts until Save. Cancel discards the draft.

Read from the original question through the prepared output, preparation,
retrieval and selected evidence, corpus reference, and model exchanges. Model
instructions and long request payloads expand in place. The corpus reference
describes the authored evidence condition and exact stored passages; it is not
a correct-answer label. Native trace links open the corresponding Chat Session.

Map displays all 100 cases using PCA of standardized structural features and
authored dimensions. Eight KMeans clusters supply 16 centroid representatives;
eight seeded random cases complete the initial sample. Cluster colors indicate
trace similarity. Large dark borders indicate sampled cases and orange rings
indicate cases with notes. Squares indicate declines; circles indicate other
outcomes. The map and sample are for discovery, not estimating failure rates.

Progress displays the taxonomy derived from human observations. Agent
suggestions remain separate until accepted. Acceptance copies the proposed note
into annotations with `author: agent_accepted`; dismissal creates no annotation.
Notes that have not been grouped remain visible. Review earlier cases again
after new modes become clear.

The server uses the Python standard library. Preparation uses the NumPy,
scikit-learn and Markdown renderer already available in the project environment.
Preparation preserves saved samples, annotations, patterns and suggestions.
Use a new directory for a different report. `records.json` is a regenerable
display cache. The hashes in `manifest.json` bind a workspace to its report,
corpus reference, and optional telemetry. Use a new directory when any of those
inputs change. Older workspaces with only a report hash must pass retained-anchor
checks before regeneration; preparation leaves existing files untouched when a
saved anchor no longer matches or its cached block content changes.
Commit human observations and their taxonomy when using them as evidence for a
change. The captured report and corpus evidence remain the original artifacts.

Optional bounded Logfire query results can be included with
`--telemetry <query-result.json>` during preparation. The current workspace
includes the query SQL, time-bounded run results, and operational span attributes
in `logfire-observations.json`. It contains no credentials. Live query results
augment the local report; handled application failures may not appear in a query
filtered only by `is_exception`.

Poll for changes during an interactive session:

```bash
uv run python scripts/watch_discovery_annotations.py \
  work/initiatives/model-evaluation/error_discovery_data/chat-synthetic/annotations.json
```

The watcher compares file content every two seconds. It reports changes for the
agent to inspect; it does not generate a taxonomy or trigger an agent turn.
After observations cover about five distinct records, scan for the human's
identified modes across both previously reviewed and unreviewed cases. Keep
suggestions subject to human acceptance.

Verify persistence and API behavior without a browser:

```bash
uv run pytest tests/test_error_discovery_chat.py -q
```
