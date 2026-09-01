# 17 — Record tokens and costs for each request

**What to build:** Every reported model request carries the token usage and
cost facts returned for that request. Available input, output, reasoning, cache,
and total token counts remain distinct. Charged and upstream costs remain
distinct, and missing values are unavailable rather than zero or estimated.

**Blocked by:** 16 — Record the actual OpenRouter route for each request.

Labels: completed

- [x] OpenRouter request records preserve every available input, output, reasoning, cache, and total token count.
- [x] Charged cost and upstream cost are recorded separately when returned.
- [x] Missing token categories and costs remain explicitly unavailable and are never reconstructed from catalog prices.
- [x] Local request records preserve applicable token usage while leaving billed cost unavailable.
- [x] Mock provider responses prove normalization and report serialization without live calls.
