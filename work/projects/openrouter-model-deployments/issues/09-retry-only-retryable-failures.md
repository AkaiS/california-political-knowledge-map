# 09 — Retry only failures that waiting can fix

**What to build:** OpenRouter failures are classified from their typed HTTP
evidence. Authentication, authorization, credit, invalid-model,
unsupported-parameter, and other invalid-request failures surface immediately.
Transport failures and retryable non-rate server failures retain bounded
request-local retry and do not pause unrelated callers.

**Blocked by:** 07 — Build a native OpenRouter chat model.

Labels: completed

- [x] Authentication, authorization, credit, invalid-model, unsupported-parameter, and other non-retryable client responses make one attempt.
- [x] Transport errors and retryable server responses retry up to the configured attempt bound.
- [x] Request-local retries do not close or delay the shared OpenRouter admission gate.
- [x] The final exhausted failure is re-raised through the real Pydantic AI Agent call.
- [x] Tests use mock responses and transport failures rather than exception-message matching or live calls.
