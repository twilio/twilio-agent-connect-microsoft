# Twilio Agent Connect for Microsoft — Deployment Guide

Production deployment options for TAC Microsoft connectors.

## Deployments

### Hosted Agents in Foundry Agent Service (Recommended)

**Architecture:** TAC + Microsoft Agent Framework run inside a Foundry Hosted
Agents sandbox, fronted by APIM for Twilio signature validation and WebSocket
passthrough. Voice + SMS.

**Key features:**

- One command (`make deploy`) provisions everything fresh — Foundry account +
  project + model deployment, Container Registry, APIM, and Key Vault

- Interactive (or pre-fill `.env`); idempotent re-runs
- No servers to manage — the agent runs in the Foundry runtime
- Bring-your-own mode (`CREATE_FOUNDRY=false`) for an existing Foundry project

**Guide:** [`agent_framework_hosted_agents/README.md`](agent_framework_hosted_agents/README.md)

**Best for:** Getting a working voice + SMS agent stood up fast, with the
fewest moving parts to operate.

---

### Azure Container Apps with Agent Framework

**Architecture:** TAC Server runs on Container Apps and creates per-conversation
Agent Framework agents. Sessions persist in Cosmos DB for horizontal scaling.
Voice (WebSocket) + SMS (HTTP).

**Key features:**

- Container Apps + Cosmos DB infrastructure (Bicep)
- Docker multi-stage build
- Managed Identity for Cosmos DB access

**Guide:** [`agent_framework_container_apps/README.md`](agent_framework_container_apps/README.md)

**Best for:** Horizontally scalable deployments with session persistence, or
when you need full control over the server and its infrastructure.

---

### Azure Container Apps with Voice Live

**Architecture:** TAC Server runs on Container Apps and streams text to Azure AI
Foundry Voice Live over WebSocket. Voice Live manages conversation state
server-side. Voice-only — no SMS.

**Key features:**

- Container Apps infrastructure (Bicep)
- Docker multi-stage build
- Voice Live WebSocket integration

**Guide:** [`voice_live_container_apps/README.md`](voice_live_container_apps/README.md)

**Best for:** Low-latency voice-only agents using Azure AI Foundry Voice Live,
without session-persistence requirements.

## Quick deploy

Each guide has the full steps. In brief:

**Hosted Agents** — interactive, provisions everything fresh:

```bash
cd deploy/agent_framework_hosted_agents
make deploy        # prompts for required values (or pre-fill .env first)
```

Teardown: `make down`.

**Container Apps (Agent Framework / Voice Live)** — via [Azure Developer CLI](https://learn.microsoft.com/en-us/azure/developer/azure-developer-cli/):

```bash
cd deploy/agent_framework_container_apps   # or voice_live_container_apps
cp .env.template .env         # fill in your values
azd env new my-tac-agent
azd env set --file .env       # load .env into the azd env (skips prompts)
azd up
```

Teardown: `azd down --purge`.

**Prerequisites:** `azd` v1.18.0+, Azure CLI (`az`), Docker, Python 3.10+
(Hosted Agents additionally uses `make`; see its guide).

For local development and testing, see [`getting_started/README.md`](https://github.com/twilio/twilio-agent-connect-microsoft/blob/main/getting_started/README.md)
