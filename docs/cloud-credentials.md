# Cloud deployment credentials

Prepare these values for the `california-knowledge-map` app on
`akaisenghor.bottle.cloud`. Keep credential values in your password manager and
the instance's Secrets app. Report completion and budget settings in chat,
without values. This guide does not create accounts, purchase credits or make
inference requests.

The required key names come from [the manifest](../cloudinabottle.toml) and
[runtime bootstrap](../src/knowledge_map/cloud_runtime.py). Use these exact
names in Secrets, without extra spaces:

| Bottle secret key | Application environment | Value to supply |
| --- | --- | --- |
| `OPENROUTER_KEY` | `OPENROUTER_API_KEY` | A dedicated inference key with a $5 monthly spending limit |
| `OPENROUTER_MODEL` | Same name | `google/gemma-4-26b-a4b-it` |
| `OPENROUTER_PROVIDERS` | Same name | `darkbloom,deepinfra/fp8` |
| `TYPESAFE_API_KEY` | Same name | Your direct TypeSafe API key for Jev |
| `LOGFIRE_API_KEY` | `LOGFIRE_TOKEN` | A write token for the chosen Logfire project |
| `LOGFIRE_URL` | `LOGFIRE_PROJECT_URL` | The URL of that same Logfire project |
| `NEO4J_PASSWORD` | Same name | A freshly generated password, at least 16 characters |
| `CLOUD_PUBLIC_ORIGIN` | Same name | `https://california-knowledge-map.akaisenghor.bottle.cloud` |

Leave optional `CLOUD_TRUSTED_PROXIES` absent until the installed router's peer
and forwarding chain have been verified. The origin has no trailing slash or
path. All eight required values must be present before startup can succeed.

## OpenRouter budget and proposed deployment

Open [OpenRouter's keys page](https://openrouter.ai/settings/keys) and create a
dedicated inference key named `california-knowledge-map-bottle`. Set its USD
spending limit to `5` and its reset to `monthly`. Confirm both saved settings
before copying the key into Secrets. A plain $5 limit with no reset is a lifetime
allowance, not the requested monthly budget. The official key API supports
`limit: 5` and `limit_reset: "monthly"`; administrative API operations require a
separate management key. Store only the inference key in Bottle.
[Key creation reference](https://openrouter.ai/docs/api/api-reference/api-keys/create-a-new-api-key),
[key management reference](https://openrouter.ai/docs/guides/overview/auth/management-api-keys).

Use OpenRouter-funded credits for this first deployment. Keep automatic credit
replenishment off if you want manual control of purchases. If BYOK is enabled
later, explicitly include its usage in the key limit and review direct provider
billing separately. The key limit covers this key's inference usage; it does
not cover credit purchase fees, other keys, Bottle, TypeSafe or Logfire.
[Budget and BYOK fields](https://openrouter.ai/docs/api/api-reference/api-keys/update-keys).
[Credit purchases and billing](https://openrouter.ai/docs/faq).

The paid model above preserves the upstream model selected by the repository's
free example, while removing the `:free` suffix. This is a different Model
Deployment. Do not copy the example provider list without checking whether its
providers serve the paid model.

As checked on October 12, 2026, OpenRouter's official endpoint API lists
Darkbloom at $0.042 per million input tokens and $0.22 per million output tokens.
DeepInfra's `deepinfra/fp8` endpoint lists $0.07 and $0.34 respectively. Both
advertise `tools`, `tool_choice`, `structured_outputs`, `response_format`,
`reasoning`, `temperature`, `top_p` and `max_tokens` support. The proposed
`darkbloom,deepinfra/fp8` policy tries the lower-price route first and allows
same-model fallback only to that specified DeepInfra endpoint.
[Official endpoint metadata](https://openrouter.ai/api/v1/models/google/gemma-4-26b-a4b-it/endpoints).

These advertisements justify a compatibility trial; no paid request has verified
them for this application. Before publication, test actual tool calls, typed
outputs and one complete Source Guide, then inspect observed provider and cost.
The application already requires support for every sent parameter and restricts
requests to the configured providers. If that trial fails, inspect the failure
before changing the approved provider list.
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
to the standard application environment. Values and provider permissions still
need the private startup checks.

Deployment requests individual grants for these keys through secrets service
version `0.1.0`. The deployment command includes `--grant-permissions-v2` so the
runtime can retrieve them. Bootstrap rejects missing or denied grants without
logging their values. Keep the app owner-only through the compatibility and
recovery checks.
[Deployment runbook](cloud-deployment.md),
[versioned secrets contract](https://github.com/cloud-in-a-bottle/cloud-in-a-bottle/tree/6ea27634d1cbfc1b29caec29b53b76d919201b97/services/secrets).

Once done, report: "Secrets configured; dedicated OpenRouter key has a $5
monthly cap; TypeSafe billing reviewed; Logfire project selected." Do not send
keys, tokens or passwords.
