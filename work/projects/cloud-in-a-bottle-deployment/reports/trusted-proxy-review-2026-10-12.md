# Trusted proxy review

The evidence supports the minimum application trust setting
`CLOUD_TRUSTED_PROXIES=127.0.0.1/32`, subject to the parent's configuration
review. No trust setting was changed by this reviewer. Leaving it absent is
also safe, but all visitors share the router peer's three-submission hourly IP
limit.

## Forwarding chain

The installed Bottle revision is
`6ea27634d1cbfc1b29caec29b53b76d919201b97`. Its
[subdomain middleware](https://github.com/cloud-in-a-bottle/cloud-in-a-bottle/blob/6ea27634d1cbfc1b29caec29b53b76d919201b97/compute_space/src/compute_space/web/middleware/subdomain_proxy.py)
honors an incoming `X-Forwarded-For` only when its socket peer is loopback Caddy.
For every other peer it substitutes that peer's own address. Its
[HTTP proxy helper](https://github.com/cloud-in-a-bottle/cloud-in-a-bottle/blob/6ea27634d1cbfc1b29caec29b53b76d919201b97/compute_space/src/compute_space/web/helpers/proxy.py)
excludes the incoming forwarding headers, then supplies the router's derived
headers to the app.

The actual Caddyfile was inspected through Bottle SSH with the existing strict
verified host-key file. Only forwarding-related lines were emitted. The file is
`/home/host/.openhost/local_compute_space/persistent_data/openhost/Caddyfile`.
The filter returned only `reverse_proxy localhost:8080`, with no
`trusted_proxies`, `trusted_proxies_strict`, `client_ip_headers` or `header_up`
overrides. This matches the
[installed generator](https://github.com/cloud-in-a-bottle/cloud-in-a-bottle/blob/6ea27634d1cbfc1b29caec29b53b76d919201b97/compute_space/src/compute_space/core/caddy.py).
Caddy's documented default ignores client-supplied forwarding values and sets
the upstream forwarding headers itself.
[Official Caddy header behavior](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy#defaults).

The packaging worker inspected only the socket-peer IP in the owned app's
Uvicorn access logs for the original HTTPS question window. The observed peer
was `127.0.0.1`. Uvicorn runs with `proxy_headers=false`, so this is the actual
socket peer. The public service's `source_ip` walks a trusted chain from right
to left and stops at the nearest untrusted address. Trusting only the observed
loopback peer allows the sanitized client address from this chain to become
the IP admission identity.

## Verification and limits

Three focused deterministic HTTP regressions passed. They cover ignoring
spoofed forwarding headers from untrusted peers, selecting the nearest
untrusted address behind a trusted peer, and preventing forwarded Host/Origin
from authorizing work or consuming admission.

No certificate paths, raw configuration, credentials, environments or request
headers were emitted. No host configuration was changed and no paid request
was made. The initial default SSH invocation lacked the existing host-key file;
the successful read used strict checking with that verified file. A wrong
Caddyfile path was corrected before reading its contents.

This is source, actual on-disk configuration and socket-peer evidence. It is not
an end-to-end hosted spoofed-XFF admission trial. The parent can approve the
single-address setting and then verify current runtime behavior. Broader
private networks and IPv6 loopback are unnecessary without corresponding peer
evidence. Recheck the chain if a CDN, external proxy, router configuration or
container networking changes.
