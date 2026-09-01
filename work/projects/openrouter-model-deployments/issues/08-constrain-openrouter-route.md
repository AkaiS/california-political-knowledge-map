# 08 — Constrain every OpenRouter route

**What to build:** Every OpenRouter request is confined to the configured
ordered provider list for the one requested model. The provider list is both a
preference order and an exclusive allowlist, fallback stays within that list,
all sent parameters must be supported, and router metadata is requested.

**Blocked by:** 07 — Build a native OpenRouter chat model.

Labels: completed

- [x] The provider request preserves the configured provider order and forbids providers outside the list.
- [x] Same-model provider fallback is enabled without permitting model substitution.
- [x] Provider eligibility requires support for every parameter sent by the application.
- [x] Router metadata is enabled on every request.
- [x] The model cache distinguishes provider order, endpoint, requested model, and effective request settings while excluding secrets.
- [x] A real Agent call through a mock transport proves the routing fields on the wire.
- [x] No provider quota, token estimate, spending ceiling, or direct Google credential is added.
