# TAC Agent Framework on Hosted Agents in Foundry Agent Service

Run TAC + Microsoft Agent Framework directly inside **Hosted Agents in
Foundry Agent Service**, with APIM in front for Twilio request signature
validation, websocket passthrough, and per-conversation sandbox
affinity.

This is the SMS + voice path; for the Container Apps equivalent, see
[`../agent_framework_container_apps`](../agent_framework_container_apps).

## Architecture

```mermaid
graph LR
    Customer([Customer])

    subgraph Twilio
        CRelay["Twilio ConversationRelay (voice)"]
        CO["Twilio Conversation Orchestrator (messaging)"]
        Memory[Twilio Conversation Memory]
    end

    subgraph Azure
        APIM[APIM<br/>signature check + form→JSON + auth]
        Foundry[Hosted Agent<br/>TAC + Agent Framework]
        AOAI[Azure OpenAI]
    end

    Customer <--> CRelay
    Customer <--> CO
    CRelay -->|TwiML POST + WSS| APIM
    CO -->|webhook POST| APIM
    APIM <-->|/invocations + /invocations_ws| Foundry
    Foundry -->|retrieve| Memory
    Foundry -->|agent.run| AOAI
```

**Flow:**
- **SMS:** Twilio CO posts JSON to `https://<apim>/twilio/webhook`.
  APIM verifies the Twilio signature, lifts `data.conversationId` onto
  `?agent_session_id=...`, and forwards to `/invocations`. The
  `TACHostedAgentsApp` dispatcher fans the body out to all
  registered messaging channels.
- **Voice:** Twilio posts a form to `https://<apim>/twilio/twiml`. APIM
  verifies the signature, converts form → JSON, and forwards to
  `/invocations`. The server returns TwiML containing
  `<Connect><ConversationRelay url="wss://<apim>/twilio/ws?agent_session_id=<CallSid>"/>`.
- **Voice WS:** Twilio dials the WSS URL. APIM verifies the signature on
  the upgrade, requires `agent_session_id` on the query, injects the
  Foundry auth + feature flag, and rewrites to `/invocations_ws`.

## What APIM does

Hosted Agents only exposes `POST /invocations` and `WS /invocations_ws`,
so APIM sits in front and adapts every Twilio request to that shape. Per
request, the policies:

1. **Validate `X-Twilio-Signature`** (HMAC-SHA1, auth token from Key
   Vault). SMS and voice-WS sign the URL only; voice TwiML signs URL +
   sorted form pairs. Mismatch → 401.
2. **Pin a sandbox** by lifting the Twilio ID onto
   `?agent_session_id=` — `data.conversationId` for SMS,
   `CallSid` for voice. Keeps a call's TwiML POST and WSS upgrade (and
   any retries) on one sandbox.
3. **Inject an Entra bearer** via APIM's managed identity
   (`resource=https://ai.azure.com`) — the Foundry endpoint isn't
   public.
4. **Convert form → JSON** (voice TwiML only; `set-body`). SMS is
   already JSON; the WS upgrade has no body.
5. **Rewrite to the Foundry route** (`/invocations` or
   `/invocations_ws`) and strip `X-Twilio-Signature` (no longer valid
   after the rewrite). The WS upgrade also requires `agent_session_id`
   on the query and injects `project_name` / `agent_name` /
   `Foundry-Features`.

## Security

APIM is the only authentication boundary in front of your agent, and it
does two things:

1. **Verifies the Twilio request signature** (the `X-Twilio-Signature`
   header) so only requests Twilio actually sent reach the agent. The
   agent layer does not re-check it — APIM strips the header after
   rewriting the URL and (for voice) the body, so the signature can no
   longer be reproduced downstream.
2. **Authenticates to the Hosted Agent.** The Foundry endpoint is not
   public; it requires an Entra bearer token, and only APIM's managed
   identity holds the `Foundry User` role. So reaching the agent means
   compromising APIM's identity, not just hitting a URL.

If you ever expose the Foundry endpoint publicly or with a shared key,
you'd need to move signature validation into `TACHostedAgentsApp`
itself — which means having APIM forward the original signed URL and
body so the signature stays reproducible.

## Prerequisites

- Azure subscription with permission to create APIM, Key Vault, and
  role assignments
- Azure CLI (`az`) and Azure Developer CLI (`azd`) installed and signed in
- An Azure OpenAI deployment (Bicep here does **not** create one)
- An existing Foundry account + project (created out of band — `azd`
  for Hosted Agents expects the project to already exist; this template
  does not create it)
- Twilio account with: Auth Token, API Key + Secret, phone number,
  and a Conversation Configuration ID

The Bicep template provisions a Key Vault for the Twilio Auth Token by
default. If you'd rather reuse an existing vault, set
`EXISTING_KEY_VAULT_NAME` (and optionally `EXISTING_KEY_VAULT_RESOURCE_GROUP`
if it lives in a different RG) — the vault must already contain a
secret named `TwilioAuthToken`.

## Deploy

`azd up` does both the APIM/Key Vault Bicep and the Foundry agent push
in one shot — `infra/main.bicep` runs first, then the agent container
is built and registered with the Foundry project.

### 1. Configure environment + build the SDK wheel

```bash
cd deploy/agent_framework_hosted_agents
cp .env.template .env
# fill in .env with your values — see "Required env vars" below

# The Dockerfile installs the SDK from a vendored wheel under wheels/
# (because TACHostedAgentsApp isn't on PyPI yet). Build it from the
# repo root:
( cd ../.. && uv build && \
  cp dist/twilio_agent_connect_microsoft-*-py3-none-any.whl \
     deploy/agent_framework_hosted_agents/wheels/ )
```

Once the SDK is published to PyPI with `TACHostedAgentsApp`, this
wheel can be removed and `requirements.txt` can install the package
from PyPI directly.

#### Required env vars (the non-obvious ones)

`.env.template` documents every variable inline — fill it in there.
These cause the most deploy failures when wrong or missing:

- **Agent name** is set by `azure.yaml`/`agent.yaml`, not by
  `HOSTED_AGENTS_AGENT_NAME`/`HOSTED_AGENTS_URL` — those must match the
  registered name (a mismatch reads as "APIM 200 / Foundry 404").
- **`HOSTED_AGENTS_URL`** must end at `/endpoint/protocols`, not the
  account root — anything else 404s every SMS webhook.
- **`AZURE_AI_PROJECT_ID`**, **`FOUNDRY_PROJECT_ENDPOINT`**, and
  **`AZURE_CONTAINER_REGISTRY_ENDPOINT`** aren't auto-discovered by
  `azd` for `host: azure.ai.agent`; without them `azd deploy` fails
  partway through.

### 2. Run `azd up`

```bash
azd env new my-tac-agent --location eastus2 --subscription <sub-id>
azd env set AZURE_RESOURCE_GROUP <rg>

# IMPORTANT: load .env into the azd environment BEFORE running azd up.
# There's no automatic import — azd only substitutes variables that are
# in its environment, so skipping this causes "missing required inputs"
# errors. Re-run it after editing .env.
azd env set --file .env

azd up
```

This:

1. Provisions APIM + Key Vault + APIs/policies via `infra/main.bicep`.
2. Builds the agent container and registers it with the Foundry project.

**Heads up:** the first `azd up` against a fresh Key Vault commonly
fails partway through with `Caller is not authorized to perform action
on resource ... getSecret/action` — APIM tries to read the seeded
secret before its `Key Vault Secrets User` role assignment has
propagated through Azure's RBAC layer. Wait ~30 seconds and re-run
`azd provision --no-state`; the second attempt always succeeds.

### 3. Grant APIM access to Foundry

Bicep can't grant roles on the Foundry account (it commonly lives
outside the subscription/RG that owns this deployment). Do this once
manually:

```bash
APIM_PRINCIPAL_ID=$(azd env get-values | grep apimPrincipalId | cut -d'"' -f2)
FOUNDRY_ACCOUNT_RESOURCE_ID=<from your Foundry portal>

az role assignment create \
  --assignee "$APIM_PRINCIPAL_ID" \
  --role "Foundry User" \
  --scope "$FOUNDRY_ACCOUNT_RESOURCE_ID"
```

(The role is named `Foundry User`, not `Azure AI User` — the latter
doesn't exist as a built-in role. This grants APIM the right to
forward requests to agents under that account.)

### 4. Configure Twilio

`azd up` prints these URLs at the end of provisioning (the
`postprovision` hook in `azure.yaml`). To see them again later, run
`azd env get-values | grep -i twilio`.

- **Phone Number → Voice URL** (POST): use `twilioVoiceTwimlUrl`.
- **Conversation Orchestrator → Webhook URL** (POST): use `twilioSmsWebhookUrl`.

(`twilioVoiceWssUrl` is informational — the agent emits the WSS URL
itself from `TWILIO_VOICE_PUBLIC_DOMAIN`, so you don't enter it in
Twilio.)

Then set `TWILIO_VOICE_PUBLIC_DOMAIN` in `.env` to the value of
`voicePublicDomain` (also printed by the hook) and re-run `azd up` so
the agent emits the correct TwiML WSS URL.

### 5. Test

Make a call or send an SMS to your Twilio number, then watch the agent
logs in the Azure AI Foundry portal (Agents → your agent → Logs).

## Teardown

```bash
azd down --purge                              # Foundry agent
az group delete --name <rg> --yes --no-wait   # APIM resource group
```

## Troubleshooting

- **APIM returns 401 "Invalid X-Twilio-Signature"** — signature
  mismatch. To see the URL APIM signed and the HMAC it computed, enable
  the APIM trace console (`Ocp-Apim-Trace` header, or the portal Test
  tab) and inspect the `twilioFullUrl` / `twilioComputedSig` variables —
  the policy deliberately does not echo these on the wire.
  Common causes: `public_domain` env on the agent doesn't match what
  Twilio is dialing; secret in Key Vault is stale; APIM's MI doesn't
  have `Key Vault Secrets User` on the vault.
- **APIM returns 400 "Missing agent_session_id"** on a WSS upgrade —
  the agent emitted a TwiML wss URL without the query param. Confirm
  the agent log shows `?agent_session_id=...` in the generated TwiML.
- **APIM returns 200 but Foundry returns 404** — `HOSTED_AGENTS_URL` is
  the account root (not the agent's `/endpoint/protocols` path) or names
  an agent azd didn't register (see "Required env vars"). Fix `.env`,
  then `azd provision --no-state`.
- **Foundry returns 502 / 504** on `/invocations` — sandbox hasn't
  finished its readiness probe. Try again after a few seconds; if
  persistent, check that `azd up` completed without errors.
- **Voice connects but agent says nothing** — the wss URL APIM rewrote
  isn't reaching `/invocations_ws`. Check the WS API's `serviceUrl` and
  `rewrite-uri` template in the policy.
- **Bicep error `RoleAssignmentExists`** — the APIM-MI → KV role is
  already granted (prior deploy, or a manual `az role assignment
  create`). Set `SKIP_KEY_VAULT_ROLE_ASSIGNMENT=true` in `.env` and
  redeploy.
- **`azd deploy` fails with `AZURE_AI_PROJECT_ID is not set`** /
  `FOUNDRY_PROJECT_ENDPOINT is required` /
  `could not determine container registry endpoint` — add the three
  azd-required envs to `.env` (see "Required env vars").
- **`azd provision` reports "no changes" after editing `.env`** — azd
  caches the deployment plan. Force a rerun with
  `azd provision --no-state`.
- **Phone numbers in the agent env appear without their leading `+`** —
  cosmetic: `azd env get-values` strips `+` from display output, but the
  underlying `.azure/<env>/.env` stores and substitutes them correctly.
- **Bicep error `enablePurgeProtection cannot be set to false`** —
  your tenant requires purge protection on Key Vaults. Leave
  `KEY_VAULT_PURGE_PROTECTION=true` in `.env` (the default).
