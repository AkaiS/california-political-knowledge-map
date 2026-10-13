# Cloud transport follow-up review

The cloud startup change applies the PRD's initial request defaults before application settings are imported. `configure_cloud_transport()` supplies a 60-second request timeout, two total transport attempts and a 15-second rate-limit wait cap. Bootstrap calls it from `configure_paths()`, and the web child calls it as the first operation in `run_web()`. Explicit operator settings remain preserved through `setdefault`.

An independent fresh-process probe exercised the actual `run_web()` function with dependency readiness, telemetry setup, app creation and Uvicorn serving replaced by controlled functions. The probe first confirmed that `knowledge_map.config` had not been imported. At the telemetry boundary, it imported the actual settings, deployment resolver and embedding HTTP client builder. Observed values were:

| Path | Timeout | Attempts | Rate-limit wait cap |
| --- | ---: | ---: | ---: |
| Cached embedding transport settings | 60 seconds | 2 | 15 seconds |
| Fresh chat request settings | 60 seconds | 2 | 15 seconds |
| Resolved OpenRouter deployment settings | 60 seconds | 2 | 15 seconds |

The constructed embedding HTTP client's read timeout was also 60 seconds. The web startup selected public mode, a 240-second overall question deadline, one worker and disabled automatic proxy-header rewriting. The existing HTTP deadline tests still cover waiting and active questions. The shared retrieval deadline remains 180 seconds.

A separate fresh process imported `cloud_runtime` without invoking a cloud startup function. Cached local transport and fresh local deployment settings remained 3,600 seconds, three attempts and a 120-second wait cap. The existing explicit-override test also passed.

The following targeted regression run passed **98 tests in 4.10 seconds**:

```bash
UV_CACHE_DIR=/tmp/ca-map-uv-cache uv run --no-sync pytest -q \
  tests/test_cloud_runtime.py tests/test_cloud_runtime_review.py \
  tests/test_public_deployment.py tests/test_public_deployment_review.py \
  tests/test_chat_web_lifecycle.py tests/test_source_guide_cancellation.py \
  tests/test_model_factory.py tests/test_openrouter_rate_limit_timing.py \
  tests/test_model_deployment.py
```

Ruff passed the changed cloud runtime and test module. No further production changes were made by this reviewer. The probes constructed configuration and an idle HTTP client, without provider requests, browser activity, live database writes or host configuration changes.

No actionable defect remains in this follow-up. These are source and controlled-process checks. The packaging worker owns rebuilding and verifying the image containing the new defaults; this note does not establish hosted latency, real provider-limit behavior or cancellation inside every synchronous worker operation.
