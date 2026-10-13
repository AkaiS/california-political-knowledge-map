# Generation evidence

On 2026-10-12 the checkout built a wheel and source distribution through `uv build --offline`. The helper passed Ruff and its executable `--help` invocation. It then ran the default production HTTP journey after the user explicitly approved Logfire telemetry.

The local model assessed `Who supported that bill?` as `needs_edit`, explaining the missing bill reference. The response retained the original wording, contained no articles, and recorded `not_searched`. The saved list and reopened response preserved the same guide and attempt. A read-only SQLite check found the question with one attempt. Restarting the owned service restored identical content and attempt identity without another search.

Evidence lives at [the proof directory](../../../../docs/verification/source-guides/2026-10-12-proof/). Start with `manifest.json`, `terminal.json`, `persisted.json`, `sqlite-proof.json`, and `cleanup.json`; `actions.json` records the request sequence and both owned process groups. Both launches exited zero. Cleanup removed the isolated state, and a separate `lsof` check found no listener on 8132. All files listed in `artifacts.json` remained after teardown.

The initial attempt is retained at [the failure directory](../../../../docs/verification/source-guides/2026-10-12-generation/). It failed during loopback-port preflight and removed its state. Automatic approval review subsequently rejected external telemetry twice. The user then approved the live run and telemetry, resolving that blocker. Future host approval requirements still apply to their own runs.

Shutdown logs contain an OpenTelemetry `KeyboardInterrupt` during an atexit metrics-reader join. Uvicorn reported completed application shutdown, the launcher exited zero, and the port closed. The run proves app teardown and retained evidence; it does not prove that every final telemetry observation was flushed. No product code was changed to address the metrics shutdown message.

The run used the configured populated Neo4j and existing llama.cpp services. It did not provision a fresh graph, install model weights, exercise Jev inference or embeddings, retrieve articles, prove answer quality, or drive a browser. Broad-topic, reading, attempt-control, independent-question, and optional helper-mode journeys remain untested. The shared app and dependency services were left running.
