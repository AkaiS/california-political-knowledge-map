# 01 — Launch the secured local chat shell

Labels: completed

## Parent

[Local Retrieval Chat](../PRD.md)

## What to build

Give a maintainer one command that starts Pydantic AI's stock browser chat on a
safe, predictable local address. The completed slice is visible without any
retrieval behavior: the command starts the server, prints the URL, and serves
the stock interface using the supported CDN and cache path.

Use a Pydantic AI release with the web chat's Host-header validation rather than
reimplementing that protection in this application. Keep the launcher explicitly
local and small; it is not a general web-server configuration surface.

## Acceptance criteria

- [x] The resolved Pydantic AI dependency is version 2.30.0 or later, and the
      stock web application rejects a non-local, non-allowed `Host` header while
      accepting loopback and localhost requests.
- [x] `ca-map chat` starts Uvicorn on `127.0.0.1:7932` by default and prints the
      browser URL.
- [x] `ca-map chat --port <port>` changes only the port; the command exposes no
      `--host` option.
- [x] Starting the command does not open a browser.
- [x] The root browser route serves Pydantic AI's stock chat frontend through
      its default CDN-hosted build and local cache.
- [x] The implementation does not vendor the offline frontend artifact or add a
      custom frontend.
- [x] Command tests invoke the existing command dispatcher with a recorded
      Uvicorn runner, and application tests exercise the ASGI boundary without
      browser automation or live network access.

## Blocked by

None — can start immediately.

## Comments

2026-09-18: Implemented the secured stock chat shell through the existing
`ca-map` dispatcher and observable agent factory. Pydantic AI 2.31.1 supplies
the CDN-backed, filesystem-cached frontend and Host-header validation. The CLI
binds only to `127.0.0.1`, defaults to port 7932, accepts only a port override,
prints the URL, and leaves browser opening to the maintainer.

Review found that FastAPI's automatic documentation routes initially sat
outside the mounted stock application's Host validation. Those routes are now
disabled, so every served route passes through Pydantic AI's protection. ASGI
tests cover the root, chat API, configuration API, and former documentation
paths for hostile hosts, plus loopback and localhost acceptance. The focused
suite passes 13 tests without browser automation or live network access.
