# Cloud deployment credentials

Prepare these values for the `california-knowledge-map` app on
`akaisenghor.bottle.cloud`. Keep credential values in your password manager and
the instance's Secrets app. Report completion and budget settings in chat,
without values. This guide does not create accounts, purchase credits or make
inference requests.

Required credentials are configured and Gemini 3.1 Flash Lite is active. The
complete HTTPS guide passed in 19.832 seconds with the expected article and
reading direction, completed search and no partial disclosure. Publication is
waiting for the owner to enable Include BYOK usage in limit on the existing
dedicated OpenRouter key, while keeping its $5 limit and monthly reset. Existing
local examples remain unchanged.

The required key names come from [the manifest](../cloudinabottle.toml) and
[runtime bootstrap](../src/knowledge_map/cloud_runtime.py). Use these exact
names in Secrets, without extra spaces:

| Bottle secret key | Application environment | Value to supply |
| --- | --- | --- |
| `OPENROUTER_KEY` | `OPENROUTER_API_KEY` | The existing dedicated $5/month key; enable Include BYOK usage in limit before publication |
| `OPENROUTER_MODEL` | Same name | `google/gemini-3.1-flash-lite` |
| `OPENROUTER_PROVIDERS` | Same name | `google-ai-studio,google-vertex/global` |
| `TYPESAFE_API_KEY` | Same name | Your direct TypeSafe API key for Jev |
| `LOGFIRE_API_KEY` | `LOGFIRE_TOKEN` | A write token for the chosen Logfire project |
| `LOGFIRE_URL` | `LOGFIRE_PROJECT_URL` | The URL of that same Logfire project |
| `NEO4J_PASSWORD` | Same name | A freshly generated password, at least 16 characters |
| `CLOUD_PUBLIC_ORIGIN` | Same name | `https://california-knowledge-map.akaisenghor.bottle.cloud` |

Optional `CLOUD_TRUSTED_PROXIES` is approved and stored as `127.0.0.1/32`, based
on verified forwarding configuration and the observed socket peer. It is active
in the web process after the private Gemini restart. The origin has no trailing
slash or path.
All eight required values must be present before startup can succeed.

## OpenRouter budget and selected deployment

Open [OpenRouter's keys page](https://openrouter.ai/settings/keys) and create a
dedicated inference key named `california-knowledge-map-bottle`. Set its USD
spending limit to `5` and its reset to `monthly`. Confirm both saved settings
and enable Include BYOK usage in limit before copying a new key into Secrets.
For this deployment, update the existing dedicated key rather than creating
another one. A plain $5 limit with no reset is a lifetime
allowance, not the requested monthly budget. The official key API supports
`limit: 5` and `limit_reset: "monthly"`; administrative API operations require a
separate management key. Store only the inference key in Bottle.
[Key creation reference](https://openrouter.ai/docs/api/api-reference/api-keys/create-a-new-api-key),
[key management reference](https://openrouter.ai/docs/guides/overview/auth/management-api-keys).

Current-key metadata shows the account's existing Google BYOK integration is
serving Gemini, with `include_byok_in_limit=false`. The verified $5/month key
allowance therefore currently excludes that usage. On the existing key, enable
Include BYOK usage in limit and save it. The required resulting settings are
`limit: 5`, `limit_reset: "monthly"` and `include_byok_in_limit: true`. Report
completion without sending its value; publication waits for that setting to be
verified. Review direct provider billing separately.
[Budget and BYOK fields](https://openrouter.ai/docs/api/api-reference/api-keys/update-keys).

Keep automatic credit replenishment off if you want manual control of purchases.
The key allowance does not cover credit purchase fees, other keys, Bottle,
TypeSafe, Logfire or unrelated Google API usage.
[Credit purchases and billing](https://openrouter.ai/docs/faq).

The cloud choice is separate from the repository's local/free example. Set the
explicit model and providers above in Bottle Secrets. Do not copy the local
example's provider policy into this hosted deployment.

As checked on October 12, 2026, the selected Gemini standard endpoints list
$0.25 per million input tokens and $1.50 per million output tokens. Both
advertise tools, forced tool choice, structured outputs, reasoning and the
current sampling/token parameters. The exclusive order permits same-model
fallback only between Google AI Studio and the specified Google Vertex endpoint.
[Official endpoint metadata](https://openrouter.ai/api/v1/models/google/gemini-3.1-flash-lite/endpoints).

Gemma's nullable-schema correction allowed one completed guide, but a further
question produced an invalid reading-order enum. The Gemini assessment trial
passed with valid dates and `relevance`, retaining prompts, validators and zero
output retries. The complete Gemini HTTPS guide also passed. Its zero response
cost represented OpenRouter billing for a BYOK-served request, not free Google
inference. Latest tracked usage is $0.00255985 OpenRouter-funded plus
$0.00601500 BYOK, totaling $0.00857485. These counters changed without another
verifier inference call, so delayed settlement or other key activity is unresolved;
they are not final or exact per-guide charges. Including BYOK in the limit
remains the required budget setting before publication.
[Deployment trial evidence](../work/projects/cloud-in-a-bottle-deployment/reports/gemini-trial-evidence-2026-10-12.md).

The application requires support for every sent parameter and restricts requests
to the configured providers. Inspect a failure before changing that policy.
[Provider routing reference](https://openrouter.ai/docs/guides/routing/provider-selection),
[project Model Deployment contract](model-deployments.md).

## TypeSafe and Logfire

Get the Jev key from the [TypeSafe console](https://console.typesafe.ai), which
the [official quick start](https://docs.typesafe.ai/introduction/quickstart)
links as the key source. Supply it as `TYPESAFE_API_KEY`. This application's
retrieval path uses the direct TypeSafe SDK; an OpenRouter key or a third-party
Jev gateway key does not replace it. Confirm your console's billing and credit
settings before public use. The OpenRouter $5 cap does not constrain Jev calls.

In [Logfire](https://logfire.pydantic.dev), select the intended project, open
Settings, select Write tokens, and create a new write token for this deployment.
Save it as `LOGFIRE_API_KEY`, and save that project's URL as
`LOGFIRE_URL`. The token appears once. Check the project's telemetry
usage settings before publication.
[Official write-token instructions](https://pydantic.dev/docs/logfire/manage/create-write-tokens/).

The deployment operator can generate a fresh `NEO4J_PASSWORD` and store it
through Bottle's authenticated Secrets API. It must contain at least 16
characters; 32 or more random characters is the proposed setting. This step
does not need a provider account or human dashboard action. The initial graph
restore does not transfer the local system database or its login password.

## Store and grant the keys

Open [your instance's Secrets app](https://secrets.akaisenghor.bottle.cloud/)
while signed in as the owner. Under Add Secret, enter the exact key name, its
value and an optional description, then select Add. Supply the three external
credentials `OPENROUTER_KEY`, `TYPESAFE_API_KEY` and `LOGFIRE_API_KEY`, plus
`LOGFIRE_URL`. For an existing entry, select Edit and then Save. These labels
come from the public source at the installed Secrets app's revision; no private
secret values were inspected.
[Installed interface source](https://github.com/cloud-in-a-bottle/secrets/blob/e49eac5a0ceb569e2eb19ccc499fb65343d371ce/secrets_app/src/secrets_app/templates/index.html).

Secret values stay outside the Git repository and build context. The four model,
provider, project and origin settings live alongside credentials because the
manifest has no arbitrary environment configuration.

The agent created the model, provider, origin and fresh Neo4j password entries
through the authenticated owner API on October 12, 2026. The password went
through request stdin and was not printed or saved in the repository. An
existing `TYPESAFE_API_KEY` entry was preserved; confirm its intended account
and billing before using it. The maintainer reports the external entries
configured under `OPENROUTER_KEY`, `LOGFIRE_API_KEY` and `LOGFIRE_URL`; key-name
inspection confirmed their presence. Cloud bootstrap maps these three entries
to the standard application environment. Private startup, active Gemini
configuration, the $5 key limit and monthly reset were verified. The BYOK flag
is false and awaits the owner's dashboard correction; the full requested cap
has not yet been established.

Deployment requests individual grants for these keys through secrets service
version constraint `==0.1.0`. The deployment command includes `--grant-permissions-v2` so the
runtime can retrieve them. Bootstrap rejects missing or denied grants without
logging their values. Keep the app owner-only until the BYOK budget flag is
verified, then complete public-route verification. Backup configuration is
deferred at the user's request.
[Deployment runbook](cloud-deployment.md),
[versioned secrets contract](https://github.com/cloud-in-a-bottle/cloud-in-a-bottle/tree/6ea27634d1cbfc1b29caec29b53b76d919201b97/services/secrets).

Once done, report: "The existing OpenRouter key has limit 5, monthly reset and
Include BYOK usage in limit enabled." Do not send
keys, tokens or passwords.
