# 01: Separate model telemetry from Request Provenance

**What to build:** Give model telemetry its own narrow path before removing the
Request Provenance recorder. An observed OpenRouter downstream provider becomes
part of the model-request span. The existing structured completion event keeps
the provider-specific operational facts that Logfire needs. HTTPX continues to
record request timing, status, and errors without blanket payload capture.

This is the expansion half of the change. Request Provenance continues to work
until the replacement report contract is proven.

**Blocked by:** None. Can start immediately.

Labels: ready-for-agent

- [ ] A successful OpenRouter model request adds its observed, non-empty
  downstream provider to the model-request span.
- [ ] A missing downstream provider remains unavailable and is not inferred
  from the configured provider order.
- [ ] Local model requests use the same telemetry path without inventing a
  downstream provider.
- [ ] Standard Pydantic AI request-model, response-model, response-identity,
  usage, calculated-cost, and model-content telemetry remains intact.
- [ ] The structured OpenRouter completion event retains BYOK use, generation
  identity, route attempts, application attempts, and exact charged and
  upstream costs.
- [ ] HTTPX instrumentation remains enabled for ordinary request timing,
  status, and errors, but blanket capture of bodies and headers is disabled.
- [ ] Request Provenance and current report output remain unchanged during this
  expansion ticket.
- [ ] Focused tests exercise local and OpenRouter model calls through
  deterministic mock transports without a live provider or Logfire project.

