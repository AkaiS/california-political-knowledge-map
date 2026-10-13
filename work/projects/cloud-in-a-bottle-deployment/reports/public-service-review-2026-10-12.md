# Independent public service verification

Reviewed the current edits in `web.py`, `public_access.py`, `adapters/source_guides.py` and the public deployment tests against the deployment PRD. HTTP checks used ASGI transports, temporary SQLite databases and controlled async sessions. They did not use a browser, live corpus mutations, external model requests or provisioning.

## Corrected finding

The first implementation consumed daily and hourly admission, then pruned expired guides inside `admission_error`. An owned guide that expired while the service remained running could pass the update ownership lookup, be deleted by that prune, and return 404 from `start_update` after spending an admission.

The implementation worker moved pruning to `start_execution`, after successful guide creation or update. The current guide then has a running attempt and is protected by retention. The independent regression ages an owned completed guide during a live application lifespan, submits an update through HTTP, and requires 202, one admission, the saved question and a new completed attempt. That regression passes. The changed boundary is [web.py](/Users/akaisenghor/Projects/california-political-knowledge-map/main/src/knowledge_map/web.py:310).

No remaining actionable defect was found in the assigned privacy, admission and lifecycle checks. This finding was corrected by the owning worker; the reviewer changed only the independent test module and this report.

## Verified behavior

| Criterion | Evidence |
| --- | --- |
| Cross-visitor and guessed-ID access | Worker HTTP tests reject list/read/update/cancel access to another visitor's guides and unowned local guides; attempts and daily admission stay unchanged. |
| Returning visitor and restart | Worker HTTP tests reopen the same guide through the original cookie after app restart; ownership and daily quota remain in SQLite. |
| Same-visitor update/cancel | Independent test updates a completed guide, then cancels its stale first attempt. The new attempt stays running and completes. A concurrent update returns 409 without consuming admission. |
| Fixed-window quota | Independent controlled-clock test rejects an hourly request at 3,599 seconds, accepts at 3,600 seconds and confirms rejection did not extend the window. After another reset, persistent daily admission still rejects further work. |
| Capacity and queued cancellation | Worker tests submit ten concurrent questions and admit only one active plus two queued. Cancelling queued work releases capacity; guessed attempts cannot cancel another guide. |
| Execution deadline and shutdown | Worker tests cover active and queued deadlines, slot release and interruption of unfinished attempts at shutdown. Local lifecycle tests also pass. |
| Streaming request limit | Worker HTTP test confirms the over-limit chunk stops further stream consumption before parsing or guide creation. Middleware checks the size before appending the chunk to its buffer. |
| Origin and Host spoofing | Independent test sends a foreign Origin with forged forwarded host/protocol from a trusted proxy peer. It receives 403 before any streamed body is consumed. A forged Host receives 421. Neither creates guides or spends daily admission. |
| Proxy IP trust | Worker tests keep untrusted forwarded headers from changing the quota identity and choose the nearest untrusted peer in a chain from configured trusted proxies. Cloud Uvicorn disables automatic proxy-header rewriting. |
| Cookie and public errors | Worker tests assert Secure, HttpOnly, SameSite=Lax cookies; provider exception sentinels do not appear in HTTP responses. Returned guide schemas omit ownership values. |
| Retention | Worker tests remove expired owned guides and their attempts while preserving local unowned guides. The independent update regression checks the corrected retention boundary. |
| Local compatibility | The local app remains explicit: setting the public environment flag alone does not change `create_app()` defaults. Existing local question, update, cancellation, restart and dependency-lifecycle tests pass. |

The hourly limiter uses the library's fixed-window policy anchored to first consumption, with in-memory counters per worker. An app restart resets hourly counters; the SQLite daily ceiling persists. These checks do not establish a rolling-hour policy or shared state for multiple workers. The deployment remains single-worker as required.

## Commands and results

The focused suite passed 84 tests in 5.80 seconds:

```bash
UV_CACHE_DIR=/tmp/ca-map-uv-cache uv run --no-sync pytest -q \
  tests/test_public_deployment.py tests/test_public_deployment_review.py \
  tests/test_chat_web.py tests/test_chat_web_lifecycle.py \
  tests/test_chat_web_corrections.py tests/test_source_guide_store.py \
  tests/test_source_guide_cancellation.py tests/test_source_guide_updates.py \
  tests/test_source_guide_recovery.py tests/test_source_guide_execution.py
```

After adding the final Origin/Host case, `tests/test_public_deployment_review.py` passed all four independent tests in 1.86 seconds. Ruff passed that test module. The parent task owns the final complete deterministic suite.

## Remaining verification

Hosted HTTPS forwarding, the actual trusted proxy address, rootless container restart, real service failure, CPU embeddings, whole-question latency and peak memory, capped provider exhaustion, off-server recovery and the final published URL remain launch checks. Controlled HTTP sessions establish application behavior without proving cancellation inside every real external SDK or worker operation. None of these fixtures spends the dedicated model budget.
