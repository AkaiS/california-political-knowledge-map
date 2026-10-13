# Cloud deployment credentials

Required credentials are configured and the app is public at
[https://california-knowledge-map.akaisenghor.bottle.cloud/](https://california-knowledge-map.akaisenghor.bottle.cloud/). It uses fixed paid
`google/gemma-4-26b-a4b-it` exclusively through `deepinfra/fp8` with the existing
OpenRouter key and credits. No extra Google or DeepInfra key is required. Do not
change the model or provider without direct user instruction; there is no
automatic model/provider fallback. The final anonymous guide passed in
17.174719 seconds. Existing local examples remain unchanged.

Keep credential values in your password manager and the instance's Secrets app.
Report completion and budget settings in chat without values. This guide does
not create accounts, purchase credits or make inference requests.

The required key names come from [the manifest](../cloudinabottle.toml) and
[runtime bootstrap](../src/knowledge_map/cloud_runtime.py). Use these exact
names in Secrets, without extra spaces:

| Bottle secret key | Application environment | Value to supply |
| --- | --- | --- |
| `OPENROUTER_KEY` | `OPENROUTER_API_KEY` | The existing dedicated $5/month OpenRouter inference key |
| `OPENROUTER_MODEL` | Same name | `google/gemma-4-26b-a4b-it` |
| `OPENROUTER_PROVIDERS` | Same name | `deepinfra/fp8` |
| `TYPESAFE_API_KEY` | Same name | Your direct TypeSafe API key for Jev |
| `LOGFIRE_API_KEY` | `LOGFIRE_TOKEN` | A write token for the chosen Logfire project |
| `LOGFIRE_URL` | `LOGFIRE_PROJECT_URL` | The URL of that same Logfire project |
| `NEO4J_PASSWORD` | Same name | A freshly generated password, at least 16 characters |
| `CLOUD_PUBLIC_ORIGIN` | Same name | `https://california-knowledge-map.akaisenghor.bottle.cloud` |

Optional `CLOUD_TRUSTED_PROXIES` is approved and stored as `127.0.0.1/32`, based
on verified forwarding configuration and the observed socket peer. It is active
in the current public web process. The origin has no trailing slash or path.
All eight required values must be present before startup can succeed.

## OpenRouter budget and selected deployment

The current dedicated key is already configured with `limit: 5` and
`limit_reset: "monthly"` and `include_byok_in_limit: true`, verified after the
user enabled BYOK counting. Paid Gemma tests counted against that allowance
and observed `is_byok: false`. Use the existing inference key; no extra Google
or DeepInfra key is necessary to purchase shared inference with OpenRouter
credits. If setting up another deployment, create its key in
[OpenRouter settings](https://openrouter.ai/settings/keys) and verify the same
limit/reset settings before use. A plain limit without reset is a lifetime
allowance. Management keys handle administration and do not replace inference
keys in Bottle.
[Key creation](https://openrouter.ai/docs/api/api-reference/api-keys/create-a-new-api-key),
[key management](https://openrouter.ai/docs/guides/overview/auth/management-api-keys).

The exclusive `deepinfra/fp8` policy excludes Google providers and their BYOK
integration. Enabling BYOK counting does not authorize a model change. Keep
that budget setting enabled; the current paid route needs no new provider key.
If direct provider billing is deliberately enabled later, review it separately.
[Budget fields](https://openrouter.ai/docs/api/api-reference/api-keys/update-keys),
[credits and BYOK](https://openrouter.ai/docs/guides/overview/auth/byok).

Keep automatic credit replenishment off if you want manual purchase control.
The allowance does not cover credit fees, other keys, Bottle, TypeSafe, Logfire
or unrelated provider usage. [Billing](https://openrouter.ai/docs/faq).

The selected paid 26B endpoint lists $0.07 per million input tokens and $0.34
per million output tokens. Strict native JSON Schema is used only for Gemma
question assessment; guidance retains its original tool-output mode. Prompts,
domain validators and zero output retries are unchanged. The final anonymous
guide returned allowed/relevance, the expected linked AB 1751 article,
completed search, no partial search and no disclosures.
[Official endpoint](https://openrouter.ai/api/v1/models/google/gemma-4-26b-a4b-it/endpoints),
[paid Gemma evidence](../work/projects/cloud-in-a-bottle-deployment/reports/gemma-paid-route-2026-10-12.md),
[strict integration review](../work/projects/cloud-in-a-bottle-deployment/reports/strict-gemma-review-2026-10-13.md).

The final anonymous smoke cost $0.00135362. Funded key usage is $0.00629775;
historical BYOK usage is $0.00601500,
unchanged during the selected paid tests. Observed combined usage is
$0.01231275 and remaining monthly allowance is $4.98768725 with a $5 limit,
monthly reset and BYOK counting enabled.
Its runtime peak was 1.745 GiB with zero swap and OOM events. Saved owner
reopening, foreign-visitor 404 responses and all seven earlier attempts in
history were verified. Earlier trial costs remain historical evidence; older
BYOK counter changes were not fully attributable to verifier activity. The cloud
configuration remains separate from the unchanged local/free example.
[Provider policy](https://openrouter.ai/docs/guides/routing/provider-selection),
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
to the standard application environment. Private startup, the $5 key limit and
monthly reset were verified. The selected paid Gemma model/provider entries were
stored through the owner API and verified active after the private restart.
The full guide and paid assessment trials verified non-BYOK funded billing.

Deployment requests individual grants for these keys through secrets service
version constraint `==0.1.0`. The deployment command includes `--grant-permissions-v2` so the
runtime can retrieve them. Bootstrap rejects missing or denied grants without
logging their values. The selected paid-Gemma guide and anonymous
public journey passed on the frozen public release, including owner reopening
and foreign-access rejection. Final billing and memory checks passed. Backup
configuration is deferred
at the user's request.
[Deployment runbook](cloud-deployment.md),
[versioned secrets contract](https://github.com/cloud-in-a-bottle/cloud-in-a-bottle/tree/6ea27634d1cbfc1b29caec29b53b76d919201b97/services/secrets).

The $5 monthly key limit and BYOK-counting setting are verified.
Keep keys, tokens and passwords out of chat and the repository.
