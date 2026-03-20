# Deployment Strategy

## Context

TAC cannot run inside Azure AI Foundry Hosted Agents directly. Hosted Agents only expose `POST /responses` with Entra ID authentication — no inbound WebSocket, no webhook passthrough, no public ingress. Twilio requires a publicly reachable server that accepts HTTP webhooks (SMS) and persistent WebSocket connections (voice).

This document defines the deployment architecture for running `tac-azure` as a bridge between Twilio and Azure AI Foundry, with a one-command deployment experience for customers.

## Architecture

```
                         ┌──────────────────────────┐
                         │         Twilio            │
                         │   (Voice + SMS infra)     │
                         └─────┬───────────────┬─────┘
                    WebSocket  │          HTTP  │
                    (voice)    │     (webhooks) │
                               │               │
                    ┌──────────▼───────────────▼──────────┐
                    │     Azure Container Apps             │
                    │     (public ingress, managed TLS)    │
                    │                                      │
                    │   ┌──────────────────────────────┐   │
                    │   │  tac-azure OmniChannelServer  │   │
                    │   │                              │   │
                    │   │  /twiml .... voice entry     │   │
                    │   │  /ws ....... voice stream    │   │
                    │   │  /webhook .. SMS             │   │
                    │   │  /health ... health check    │   │
                    │   └──────────────┬───────────────┘   │
                    │                  │                    │
                    │   ┌──────────────▼───────────────┐   │
                    │   │  Cosmos DB (serverless)       │   │
                    │   │  Session store                │   │
                    │   └──────────────────────────────┘   │
                    └──────────────────┬───────────────────┘
                                       │
                            HTTPS      │  Entra ID auth
                     POST /responses   │
                                       │
                    ┌──────────────────▼───────────────────┐
                    │     Azure AI Foundry                  │
                    │     Hosted Agent (sandbox)            │
                    │                                      │
                    │     Agent logic, tools, LLM calls     │
                    └──────────────────────────────────────┘
```

### Component responsibilities

| Component | Role |
|---|---|
| **Azure Container Apps** | Public-facing container runtime. Accepts Twilio webhooks and WebSocket connections. Managed TLS, auto-scaling, managed identity. |
| **tac-azure OmniChannelServer** | Bridge layer. Translates Twilio protocols (ConversationRelay WebSocket, SMS webhooks) into Foundry Responses API calls. Manages voice session lifecycle and SMS conversation continuity. |
| **Cosmos DB (serverless)** | Persistent session store for `AgentSession`. Enables SMS multi-turn continuity, horizontal scaling, and session durability across restarts. |
| **Azure AI Foundry Hosted Agent** | The customer's agent. System prompt, model, tools, agent code. Updated independently of the bridge. |

### Decoupling principle

The bridge (Container Apps) and the agent (Hosted Agents) are decoupled at the `/openai/responses` API boundary. Customers iterate on their agent — change prompts, models, tools, deploy new versions — without touching the bridge. The bridge is "deploy once" infrastructure.

## Tool Calling

TAC tools (memory recall, knowledge base search, Flex escalation) and hosted agent tools (code interpreter, web search, custom business logic) coexist through the Responses API's standard tool calling protocol.

Hosted Agents is a first-party provider for Microsoft Agent Framework, and both support tool calling natively. The Responses API distinguishes two tool types:

- **Hosted tools** — defined in the hosted agent, executed server-side in the sandbox (e.g. code interpreter, web search, custom agent tools)
- **Function tools** — defined by the client (the bridge), returned to the client for execution when the model calls them (e.g. TAC memory, knowledge, escalation)

Agent Framework manages the tool calling loop automatically. Both tool types work in the same turn.

```
Bridge: agent.run("What's my plan?")
│
├─ Agent Framework sends to hosted agent:
│    POST /responses { input: "...", tools: [memory_recall, knowledge_search] }
│
├─ Hosted agent LLM reasons, calls code_interpreter
│    → executed server-side in sandbox
│
├─ LLM calls memory_recall
│    → returned to bridge via Responses API protocol
│    → Agent Framework executes locally (tac.memora_client)
│    → result sent back to hosted agent
│
├─ LLM continues reasoning with both tool results
│
└─ Final response streamed back to Twilio
```

The `create_agent` factory in the bridge registers TAC tools on the Agent Framework `Agent`. The hosted agent's LLM sees these alongside its own tools and calls whichever it needs:

```python
def create_agent(session):
    client = AzureOpenAIResponsesClient(...)  # points to hosted agent

    tools = [
        create_memory_recall_tool(tac, session),      # executed in bridge
        create_knowledge_tool(tac, kb_id, ...),        # executed in bridge
    ]
    # Hosted agent's own tools (code_interpreter, etc.) are defined
    # server-side and available automatically — no bridge config needed.

    return Agent(client=client, tools=tools)
```

Customers add or remove TAC tools in `create_agent` without changing the hosted agent. They add or remove hosted agent tools without changing the bridge. The two are independent.

## Session Store: Cosmos DB Serverless

### Why Cosmos DB

| Requirement | Cosmos DB serverless |
|---|---|
| Enterprise SLA | 99.99% availability |
| No capacity planning | Pay-per-request, scales to zero |
| Session expiry (GDPR/compliance) | Built-in TTL — documents auto-delete after configurable period |
| Managed identity auth | `DefaultAzureCredential`, no connection strings |
| Serialization headroom | 2MB document limit (vs 1MB for Azure Table Storage) — conversation history can grow |
| Automatic backups | Continuous backup with 7-day retention (serverless default) |
| Encryption | At rest by default |
| Async SDK | `azure-cosmos` supports native async |
| Cost | Negligible — ~$0.25/million reads, ~$1.25/million writes, $0.25/GB/month storage |

### Implementation: `AzureCosmosSessionStore`

Ships as a built-in `AgentSessionStore` implementation in the `tac-azure` package.

```python
class AzureCosmosSessionStore:
    """Enterprise session store backed by Cosmos DB serverless.

    Auto-configures from COSMOS_ENDPOINT env var + DefaultAzureCredential.
    Sessions auto-expire via TTL.
    """

    def __init__(
        self,
        endpoint: str | None = None,          # defaults to COSMOS_ENDPOINT env var
        database: str = "tac",
        container: str = "sessions",
        ttl_seconds: int = 7 * 86400,         # 7 days
        credential: TokenCredential | None = None,  # defaults to DefaultAzureCredential
    ): ...

    async def load(self, session_id: str) -> AgentSession | None:
        # Point read by session_id (partition key = session_id)
        # Deserialize with AgentSession.from_dict()

    async def save(self, session_id: str, session: AgentSession) -> None:
        # Upsert with session.to_dict() + TTL field
```

Design choices:

- **Partition key = `session_id`** — every operation is a point read/write (single-digit ms, cheapest RU cost)
- **TTL on every document** — sessions auto-expire (default 7 days). No cleanup code, no cron jobs
- **Managed identity by default** — no connection strings to manage or rotate
- **Upsert on save** — idempotent, no create-vs-update branching

### Auto-configuration

`OmniChannelServer` auto-detects the session store with zero customer code:

```python
# Customer's server.py — no session store code
server = OmniChannelServer(
    tac=tac,
    create_agent=create_agent,
    channels=["voice", "sms"],
)
```

Resolution order:

1. Explicit `session_store=` parameter (customer override)
2. `COSMOS_ENDPOINT` env var detected → `AzureCosmosSessionStore()`
3. Fallback → `InMemoryAgentSessionStore()` (local dev)

The Bicep template sets `COSMOS_ENDPOINT` on the Container App automatically, so production uses Cosmos with zero configuration. Local dev uses in-memory with no setup.

## Infrastructure: What the Bicep Template Provisions

### Resources

| Resource | SKU / Config | Purpose |
|---|---|---|
| Container Apps Environment | Consumption | Container runtime with Log Analytics |
| Container App | 1 replica min, managed identity, ingress enabled | Runs the tac-azure bridge |
| Cosmos DB Account | Serverless capacity mode | Session store backend |
| Cosmos DB Database | `tac` | Database container |
| Cosmos DB Container | `sessions`, partition key `/session_id`, TTL enabled | Session documents |

### RBAC assignments (automated)

| Principal | Role | Scope | Purpose |
|---|---|---|---|
| Container App managed identity | `Azure AI Developer` | Foundry project | Call `/openai/responses` on hosted agent |
| Container App managed identity | `Cosmos DB Built-in Data Contributor` | Cosmos DB account | Read/write session documents |

### Secrets

| Secret | Source | Notes |
|---|---|---|
| `TWILIO_AUTH_TOKEN` | Container Apps secret | For webhook signature validation |
| `TWILIO_TAC_API_KEY` | Container Apps secret | TAC API key |
| `TWILIO_TAC_API_TOKEN` | Container Apps secret | TAC API token |

All Azure-side auth uses managed identity (`DefaultAzureCredential`) — no Azure secrets to manage.

### What the template does NOT provision

The following are expected to exist already (from the customer's Hosted Agents setup):

- Azure AI Foundry account and project
- Azure Container Registry (ACR)
- The hosted agent deployment itself

## Deliverables

### Repository structure

```
deploy/
└── container-apps/
    ├── azure.yaml              # azd manifest
    ├── Dockerfile              # Bridge container image
    ├── server.py               # Minimal OmniChannelServer entry point
    ├── requirements.txt        # Pinned dependencies
    ├── .env.example            # All required env vars documented
    └── infra/
        ├── main.bicep          # Container Apps + Cosmos DB + RBAC
        ├── main.parameters.json
        └── abbreviations.json
```

### Dockerfile

Standard Python container. No special infrastructure requirements beyond what Container Apps provides.

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
```

### `server.py` (template entry point)

Minimal bridge server. Customers copy this and add their `create_agent` factory:

```python
from tac import TAC, TACConfig
from tac_azure import OmniChannelServer
from agent_framework import Agent
from agent_framework.azure_ai import AzureOpenAIResponsesClient

def create_agent(session):
    client = AzureOpenAIResponsesClient(...)  # points to hosted agent
    return Agent(client=client)

tac = TAC(config=TACConfig.from_env())
server = OmniChannelServer(
    tac=tac,
    create_agent=create_agent,
    channels=["voice", "sms"],
)
app = server.app  # uvicorn entrypoint
```

### Bicep template (`infra/main.bicep`)

Approximately 150-200 lines. Provisions:

1. Container Apps Environment (with Log Analytics workspace)
2. Container App (with system-assigned managed identity, ingress with WebSocket support)
3. Cosmos DB account (serverless) + database + container
4. RBAC role assignments for managed identity → Foundry + Cosmos DB
5. Environment variables and secrets wired to the Container App

## Customer Experience

### Initial deployment

```bash
cd deploy/container-apps

# Configure
azd init
azd env set AZURE_AI_PROJECT_ENDPOINT "https://..."
azd env set TWILIO_TAC_API_KEY "SK..."
azd env set TWILIO_TAC_API_TOKEN "..."
azd env set TWILIO_AUTH_TOKEN "..."
azd env set TWILIO_TAC_ACCOUNT_SID "AC..."
azd env set TWILIO_TAC_PHONE_NUMBER "+1..."
azd env set TWILIO_TAC_CONVERSATION_SERVICE_SID "conv_..."

# Deploy everything
azd up
```

`azd up` provisions all infrastructure, builds the container, deploys it, and outputs the public URL.

### Configure Twilio

Copy the Container App URL from `azd up` output and configure in Twilio console:

- Voice webhook: `https://<app>.azurecontainerapps.io/twiml`
- SMS webhook: `https://<app>.azurecontainerapps.io/webhook`

### Update the agent (independent of bridge)

Customers use the Hosted Agents CLI or `azd` to iterate on their agent:

```bash
# In the hosted agents repo — no changes to the bridge
foundry-agent deploy
```

The bridge continues calling the same `/openai/responses` endpoint. New agent versions take effect immediately.

### Update the bridge (rare)

Only needed for Twilio-side changes (new phone number, add/remove channels, upgrade tac-azure):

```bash
cd deploy/container-apps
azd deploy    # rebuilds and redeploys container only
```

## Scaling

### Default: single replica

Start with `min: 1, max: 1`. In-memory session store works alongside Cosmos for this configuration. Suitable for moderate traffic (tens of concurrent calls).

### Horizontal scaling

Container Apps auto-scales on concurrent HTTP connections. Each voice call = one WebSocket = one connection, making this a natural scaling signal.

When scaling beyond one replica:

- **SMS** — Cosmos DB session store ensures any replica can handle any conversation. No sticky sessions needed.
- **Voice** — WebSocket connections are inherently sticky (pinned to one replica for the call duration). No special configuration. Container Apps respects active connections during scale-down (`terminationGracePeriodSeconds`).

### Scaling configuration

```bicep
scale: {
  minReplicas: 1
  maxReplicas: 10
  rules: [
    {
      name: 'http-connections'
      http: { metadata: { concurrentRequests: '50' } }
    }
  ]
}
```

## Security

| Concern | Mitigation |
|---|---|
| Twilio webhook authenticity | `validate_webhooks=True` (default) — verifies Twilio HMAC signatures on every inbound request |
| Azure API auth | Managed identity with `DefaultAzureCredential` — no API keys or connection strings for Azure services |
| Twilio secrets | Stored as Container Apps secrets, injected as env vars — not in source code or container image |
| Session data encryption | Cosmos DB encrypts at rest by default (Microsoft-managed keys; customer-managed keys available) |
| Network | Container Apps ingress provides managed TLS. Outbound to Foundry uses HTTPS with Entra ID bearer tokens |
| Session expiry | Cosmos DB TTL auto-deletes session documents (default 7 days) — no stale PII accumulation |

## Cost Estimate

For a low-to-moderate traffic deployment (hundreds of calls/day, thousands of SMS/day):

| Resource | Estimated monthly cost |
|---|---|
| Container Apps (1 replica, 0.5 vCPU / 1GB) | ~$15-30 |
| Cosmos DB serverless (session read/writes) | < $1 |
| Cosmos DB storage (session documents) | < $1 |
| **Total bridge infrastructure** | **~$15-30/month** |

Foundry Hosted Agents, ACR, and LLM inference costs are separate and already part of the customer's existing Azure spend.
