# ChatGPT subscription inference research, 2026-10-01

The September 29, 2026 DevDay announcement does introduce subscription-funded inference for third-party apps through Sign in with ChatGPT. Eligible Plus and Pro users can authorize an app to use their plan. OpenAI describes availability for open-source partners and selected private clients, with commercial sign-in still in a limited trial. [DevDay announcement](https://learn.chatgpt.com/docs/whats-new/devday-2026).

This changes the earlier cloud-hosting research. Subscription inference deserves consideration for personal use and eligible integrations. The official documentation does not establish that one developer's subscription can fund an anonymous public portfolio website.

## Which deployment does it cover?

| Scenario | What the published documentation establishes |
| --- | --- |
| Run an eligible open-source app locally with your own subscription | Documented. The app can register an OAuth client and request plan inference without an API key or client secret. [Quickstart](https://developers.openai.com/siwc/quickstart). |
| Run that app on your own remote VPS | Explicitly documented for an open-source app on a self-hosted VM. Complete OAuth locally, securely transfer the protected credentials, retain a distinct stable VM host ID, and let the VM refresh tokens. [VM guide](https://developers.openai.com/siwc/token-sharing-open-source/self-hosted-vms). |
| Let visitors sign in and consume their own Plus/Pro allowances | This is the announced participating-app model. A remotely hosted deployment still needs eligibility confirmed through OpenAI's interest process. [Quickstart](https://developers.openai.com/siwc/quickstart), [plan usage overview](https://developers.openai.com/siwc/token-sharing-open-source). |
| Let anonymous portfolio visitors consume your personal subscription | Unconfirmed. The VM guide addresses the selected account's self-hosted installation, and the overview directs paid or remotely hosted app developers to an interest form. Neither establishes blanket eligibility for a shared public service. [Plan usage overview](https://developers.openai.com/siwc/token-sharing-open-source). |

The distinction is the app's use and eligibility, not simply whether the machine lives in a cloud datacenter. An open-source VM running for its owner has explicit guidance. A public service serving unrelated visitors needs a separate answer from OpenAI. Publishing source code alone is insufficient evidence that a hosted service qualifies.

## What the subscription pays for

Requests consume the existing Codex/ChatGPT Work allowance included in the user's plan. Connecting an app creates no extra allowance. Users can set an app's weekly cap as a percentage of their overall allowance and can choose whether credits fund further usage. Signing in and authorizing plan consumption are separate permissions. The app does not gain access to ChatGPT conversations or memories. [User guide](https://learn.chatgpt.com/docs/sign-in-with-chatgpt).

For this project, subscription-funded inference could reduce the marginal cost of model requests within the available allowance. Hosting the web app, Neo4j, and the embedding service still needs compute and storage. It also competes with the account's existing coding usage. The fetched docs provide no reliable conversion from a plan allowance into a fixed monthly number of political questions, so a capacity estimate needs actual measurement.

## Integration implications

This route uses OAuth credentials for eligible Responses API requests. The open-source flow requires PKCE, identity validation, consent, a persistent host identifier, and protected credential storage. Its callback is HTTP loopback on `127.0.0.1`, which explains why the VM procedure completes sign-in locally first. [Registration guide](https://developers.openai.com/siwc/token-sharing-open-source/sign-in).

Access tokens last one hour. Refresh tokens last 30 days, and successful refresh rotates them with a fresh lifetime. The app must persist the replacement safely. [Token reference](https://developers.openai.com/siwc/token-sharing-open-source/token-reference).

HTTP inference requires `stream: true`, `store: false`, and request history in `input`. The route rejects several ordinary settings, including `temperature`, `top_p`, `max_output_tokens`, and HTTP `previous_response_id`. Use instructions or developer messages rather than explicit system-message items. Function/custom tools require namespaces or `additional_tools`. [Preview limitations](https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations).

Repository assessment, untested: the current deployment schema supports local and OpenRouter routes, and model creation uses Chat Completions. Adding subscription inference requires a Responses deployment route, OAuth renewal, and compatibility checks for tool calls and structured outputs. Visitor-funded usage also requires account-specific credentials and agent routing; the current web startup builds application-wide agents. The existing EmbeddingGemma retrieval model remains a separate dependency. See [deployment schema](/Users/akaisenghor/Projects/california-political-knowledge-map/main/src/knowledge_map/schemas/model_deployment.py), [model construction](/Users/akaisenghor/Projects/california-political-knowledge-map/main/src/knowledge_map/utils/models.py), and [chat startup](/Users/akaisenghor/Projects/california-political-knowledge-map/main/src/knowledge_map/chat_startup.py).

## Recommendation

Explore this first for personal operation on a VPS or a local open-source installation. For the portfolio website, retain the earlier inexpensive API-backed demo plan until OpenAI confirms hosted eligibility and whether owner-funded anonymous use is allowed. Alternatively, an approved visitor-sign-in flow could shift inference consumption to each visitor's own plan, at the cost of login friction and subscription eligibility. No integration, sign-in, or resource purchase was performed during this research.
