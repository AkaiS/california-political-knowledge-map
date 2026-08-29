# 10 — Honor OpenRouter rate-limit timing for one request

**What to build:** One OpenRouter request that receives a `429` releases its
response and connection, waits for the best server-directed deadline available,
and retries the same pending request. Reset information wins over
`Retry-After`, which wins over bounded exponential backoff with jitter.

**Blocked by:** 09 — Retry only failures that waiting can fix.

Labels: completed

- [x] A valid rate-limit reset header determines the wait before any other timing source.
- [x] `Retry-After` determines the wait when no valid reset value is available.
- [x] Missing or invalid timing headers fall back to bounded exponential backoff with jitter.
- [x] Every wait respects the configured wait cap and every request respects the configured attempt count.
- [x] The failed response and connection are released before the wait begins.
- [x] Controlled-clock Agent tests cover each timing source, success after retry, and exhausted attempts without wall-clock sleeping.
