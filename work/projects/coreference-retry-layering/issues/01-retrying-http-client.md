# 01 — A retrying HTTP client behind every Ollama model

**What to build:** A rate limit or a dropped connection is retried at the failed
request, inside the model call that hit it. A connection reset while the
Coreference Critic is judging the third round of Mention Spans no longer
discards the annotation and every accepted verdict — the request is retried and
the run continues.

The model factory builds one retrying httpx client per resolved model and base
URL and hands it to the Ollama provider, so Coreference Resolution, Entity
Extraction, Selector Healing, and the Relevance Filter are covered without
opting in. The wait comes from the parsed `Retry-After` header.

This ticket only adds. The Story Pipeline's own retry stays where it is and
simply stops firing, so nothing breaks while the new path proves itself.

**Blocked by:** None — can start immediately.

Labels: ready-for-agent

- [x] The model factory builds an httpx client whose transport retries `HTTPStatusError` and httpx transport errors, waits using the parsed `Retry-After` header capped at a configured maximum, stops after a configured attempt count, and re-raises the final failure.
- [x] A 429 response becomes a retryable exception rather than reaching the caller as a response.
- [x] The retrying client is passed to the Ollama provider, so an agent constructed by any adapter inherits it.
- [x] A transport settings block holds the attempt count, the rate limit wait cap, and the request timeout, each overridable by environment variable.
- [x] Repeated agent construction for the same model name and base URL shares one provider and one connection pool.
- [x] The Ollama null-content patch still applies to every model the factory returns.
- [x] A test drives a real agent call through an injected `httpx.MockTransport` and shows a 429 carrying `Retry-After` followed by a 200 yielding one successful run.
- [x] A test shows the configured attempt count being exhausted and the final failure re-raised.
- [x] The existing suite passes unchanged; nothing is deleted in this ticket.
