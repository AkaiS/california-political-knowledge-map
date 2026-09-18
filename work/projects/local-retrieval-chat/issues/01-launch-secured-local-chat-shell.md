# 01 — Launch the secured local chat shell

Labels: ready-for-agent

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

- [ ] The resolved Pydantic AI dependency is version 2.30.0 or later, and the
      stock web application rejects a non-local, non-allowed `Host` header while
      accepting loopback and localhost requests.
- [ ] `ca-map chat` starts Uvicorn on `127.0.0.1:7932` by default and prints the
      browser URL.
- [ ] `ca-map chat --port <port>` changes only the port; the command exposes no
      `--host` option.
- [ ] Starting the command does not open a browser.
- [ ] The root browser route serves Pydantic AI's stock chat frontend through
      its default CDN-hosted build and local cache.
- [ ] The implementation does not vendor the offline frontend artifact or add a
      custom frontend.
- [ ] Command tests invoke the existing command dispatcher with a recorded
      Uvicorn runner, and application tests exercise the ASGI boundary without
      browser automation or live network access.

## Blocked by

None — can start immediately.
