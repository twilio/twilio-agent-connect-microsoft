# tac-azure — Architecture Review

## What is this?

A Python SDK for building Twilio voice + SMS agents using **Microsoft Agent Framework** (successor to Semantic Kernel, currently in RC).

Same role as `strands-communications-twilio` but for the Azure/Microsoft ecosystem.

## Azure Context for AWS-Oriented Readers

| AWS | Azure equivalent |
| --- | --- |
| Bedrock Runtime (`Converse` / `InvokeModel`) | [Azure OpenAI](https://learn.microsoft.com/en-us/azure/ai-services/openai/) — same OpenAI API shape, hosted in Azure |
| [Agents for Bedrock](https://docs.aws.amazon.com/bedrock/latest/userguide/agents-how.html) | [Azure AI Foundry Agent Service](https://azure.microsoft.com/en-us/products/ai-foundry/agent-service/) — define agents in portal UI, invoke via REST (threads/runs) |
| [AgentCore Runtime](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agents-tools-runtime.html) | [Foundry hosted agents (preview)](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/hosted-agents) — your container, their ingress |
| [Strands Agents](https://strandsagents.com/) | [Microsoft Agent Framework](https://learn.microsoft.com/en-us/agent-framework/overview/) (successor to Semantic Kernel) |

**Microsoft Agent Framework** (≈ Strands Agents):
- Open-source SDK — Python + .NET, `Agent` type with tool calling loop + streaming
- **Provider-agnostic** — Azure OpenAI, OpenAI, Anthropic, Bedrock, Ollama, Foundry Agent Service, more ([full list](https://learn.microsoft.com/en-us/agent-framework/agents/providers/?pivots=programming-language-python))
- **Standard interface across the spectrum** — same `Agent` API whether the backend is raw chat completions, a locally-hosted Ollama model, or a fully managed Foundry Agent Service with server-side threads/tools. You build and invoke agents the same way; the framework abstracts the provider differences
- **Multi-agent orchestration** — built-in support for complex workflows with multiple cooperating agents (handoffs, sequential/parallel pipelines, supervisor patterns)
- Swap the provider config; your code stays the same (Strands is Bedrock-only)
- Currently in [Release Candidate](https://devblogs.microsoft.com/foundry/microsoft-agent-framework-reaches-release-candidate/) — API surface frozen

**Azure AI Foundry** (≈ Bedrock console + SageMaker):
- **Foundry Agent Service** — define agents (model, tools, instructions) in a portal, invoke via REST
- This SDK connects to portal-defined agents via `agent_id` — build in UI, serve over Twilio without redefining in code ([docs](https://learn.microsoft.com/en-us/agent-framework/agents/providers/azure-ai-foundry?pivots=programming-language-python))

**Why TAC can't run inside Azure's managed runtime:**
- AgentCore gives you `/ws` (WebSocket) + custom JSON passthrough → ConversationRelay connects directly
- Foundry hosted agents only expose `POST /responses` with a fixed schema — no WebSocket, no webhook passthrough
- So this SDK provides its own FastAPI server (`OmniChannelServer`) deployed as a standalone container

Full three-cloud comparison: [hyperscaler-comparison.md](../sierra-example-agents/docs/hyperscaler-comparison.md)

## SDK Design

Three layers — customer code on top, shared TAC foundation on the bottom. MS Agent Framework and Twilio are external dependencies on either side:

```
                                                        Microsoft Agent Framework
                                                        (standard Agent interface
                                                         across any provider)
                                                              │
┌─────────────────────────────────────────────────┐           │
│  Customer code                                  │           │
│  • Picks provider (Azure OpenAI, Foundry  ──────────────────┘
│    Agent Service, OpenAI, Ollama, etc.)         │
│    Framework wraps it as a standard Agent       │
│  • Defines create_agent(ConversationSession)    │
│    -> Agent                                     │
│  • System prompts, custom tools                 │
│  • Optionally provides AgentSessionStore impl   │
└──────────────────────┬──────────────────────────┘
                       │ passes create_agent + AgentSessionStore to
┌──────────────────────▼──────────────────────────┐
│  OmniChannelServer (batteries-included)         │
│  • Pre-wired FastAPI routes                     │
│  • Webhook signature validation                 │
│  • on_startup hook                              │
└──────────────────────┬──────────────────────────┘
                       │ delegates to
┌──────────────────────▼──────────────────────────┐
│  AgentFrameworkBridge (core logic)                │
│  • Calls create_agent(ConversationSession)      │
│    per call/message                             │
│  • Calls agent.run(session=AgentSession)        │
│    (provider-agnostic)                          │
│  • AgentSessionStore: load/save AgentSession    │
│    around each agent.run()                      │
│  • Memory auto-injection, on_message hook       │
│  • Tool wrappers (thin — delegate down to TAC)  │
└──────────────────────┬──────────────────────────┘
                       │ delegates to
┌──────────────────────▼──────────────────────────┐
│  TAC (shared with Strands SDK)                  │
│  • VoiceChannel (ConversationRelay WS) ────────────── Twilio Voice
│  • SMSChannel (webhooks) ──────────────────────────── Twilio SMS
│  • MemoryClient, KnowledgeClient                │
│  • TACTool system, webhook signature validation │
│  • Provides ConversationSession to handler  ──┐ │
└───────────────────────────────────────────────┼─┘
                                                │
                          (ConversationSession flows up to
                           handler, passed to create_agent)
```

Customer code can use OmniChannelServer directly, or use AgentFrameworkBridge with their own FastAPI app for full control over routing and middleware.

This SDK is a thin orchestration layer. Tool logic and webhook validation live in TAC — not reimplemented here.

## Deployment Patterns

| | **Self-contained** | **Foundry Agent Service** | **Hosted Agents** |
| --- | --- | --- | --- |
| **Agent defined in** | Code (your `create_agent` factory) | Foundry portal or API — no agent code needed | Code (your container) |
| **Agent runs in** | Same container as Twilio proxy | Microsoft-managed Foundry backend | Azure-managed container (Hosted Agents runtime) |
| **Provider** | Any (Azure OpenAI, OpenAI, Ollama, etc.) | Foundry Agent Service (`AzureAIAgentClient`) | Exposes `POST /responses` (Responses API schema) |
| **Twilio proxy** | Built-in (`OmniChannelServer` in same process) | Separate container running `OmniChannelServer`, calls Foundry API | Separate container running `OmniChannelServer`, calls hosted agent's `/responses` endpoint |
| **Agent reusable outside Twilio?** | No — agent only exists in-process | Yes — any client can call the Foundry API | Yes — any client can call the `/responses` endpoint |
| **Session/thread management** | Client-side (`AgentSessionStore`) | Server-side (Foundry manages threads) | Depends on agent implementation |
| **Supported by this SDK today?** | Yes | Yes | Yes — point `AzureOpenAIResponsesClient` at the hosted agent's URL (same Responses API schema) |

**Pattern 1 — Self-contained** is the simplest: one container, agent defined in code, deploy anywhere. Best for prototyping or when the agent only serves Twilio.

**Pattern 2 — Foundry Agent Service** decouples the agent from Twilio. The agent is defined in the portal (or via API) — no agent code in your repo. This SDK's container is just a Twilio ↔ Foundry bridge. The same agent can be invoked by a web app, mobile app, or internal services without touching the Twilio layer.

**Pattern 3 — Hosted Agents** is for customers who want to write agent code but have Azure manage the infra. Their agent container runs in Azure's managed runtime, exposed as `POST /responses`. A separate container runs this SDK to proxy Twilio traffic. Since Hosted Agents exposes the same Responses API schema, you point `AzureOpenAIResponsesClient` at the hosted endpoint — no special adapter needed.

## What's New vs Strands

See [DIFFERENCES_VS_STRANDS.md](./DIFFERENCES_VS_STRANDS.md) for the full comparison. Headlines:

- Multi-provider LLM support (not Bedrock-only)
- Uses `Agent` directly instead of custom `AgentProxy` ABC
- Pluggable `AgentSessionStore` (Redis/CosmosDB) instead of local filesystem
- No handler/server code duplication — server delegates to handler
- Memory auto-injection into prompts (Strands only exposes memory as a tool)
- Built-in webhook signature validation
- Channel selection (`voice`, `sms`, or both)

Some features are partly enabled by a **newer TAC pin** (unified `on_message_ready` for voice+SMS, `auto_retrieve_memory` flag, `idempotency_token`). Strands gets these once its TAC pin is bumped.

## AgentSessionStore

### What is `AgentSession`?

`AgentSession` is Microsoft Agent Framework's abstraction for agent conversation state. What it holds depends on the provider:
- **Foundry Agent Service** — the server-side `thread_id` (stored as `session.service_session_id`), so subsequent messages reuse the same Foundry thread
- **Responses API / Chat Completions** — full message history (via `InMemoryHistoryProvider`), so the agent has multi-turn context

Agent Framework passes `AgentSession` to every `agent.run()` call. It supports serialization via `to_dict()` / `from_dict()`.

### Why do we need `AgentSessionStore`?

The problem: **SMS is stateless** — each webhook is an independent HTTP request with no shared memory. Voice is stateful during the call (WebSocket), but state is lost when the call ends.

Without persistence:
- SMS loses conversation context between messages (Foundry creates a new thread every time, Chat Completions starts with empty history)
- Voice sessions can't be audited or recovered

`AgentSessionStore` is a protocol (structural typing) with two methods:
- `load(session_id)` → retrieve a previously saved `AgentSession`
- `save(session_id, session)` → persist after `agent.run()`

### How it's used

- **SMS** — load before each message, save after `agent.run()`. Enables multi-turn conversations.
- **Voice** — session lives in-memory during the WebSocket call. Background-saved (fire-and-forget) after each utterance for auditing and Foundry thread durability. Final save on disconnect.
- **Default** — `InMemoryAgentSessionStore` (dict). Fine for single-instance.
- **Scaling** — swap for Redis, CosmosDB, etc. Same protocol, no code changes in the handler.

### Comparison with Strands

Strands uses `FileSessionManager` — writes to local filesystem, doesn't scale horizontally. `AgentSessionStore` is provider-agnostic and pluggable by design.

## Key Design Decisions

| Decision                       | Rationale                                                                                                         |
| ------------------------------ | ----------------------------------------------------------------------------------------------------------------- |
| Use `Agent` type directly      | Already depends on agent_framework; custom protocol adds complexity without value                                 |
| `AgentSessionStore` interface       | Decouples persistence from handler; enables Redis/CosmosDB without code changes                                   |
| Tools delegate to TAC          | Avoids reimplementing tool logic; uses `TACTool.implementation` for clean callable                                |
| Background voice session saves | `asyncio.create_task()` — never blocks voice latency; enables auditing                                            |
| `on_message` hook              | Lets customers customize memory formatting without subclassing                                                    |
| Sync `create_knowledge_tool`   | Async metadata fetch is separate (`fetch_knowledge_base_info`); tool creation stays sync for use in agent factory |

## Open Questions

- Naming — do we tie to Azure or keep it generic (users don't have to use Azure)?
  - Repo: `azure-twilio-agent-connect-python` vs `microsoft-agent-framework-twilio-agent-connect-python`?
  - Package: `azure_tac` vs `microsoft_agent_framework_tac`?
- Python-only OK? MS Agent Framework supports Python + .NET only.
- OK to depend on MS Agent Framework while in RC?
- Do we want auto memory fetching and injection on or off by default?
- Should we document an opinionated deployment guide for azure?
- Generate/export SDK code from Foundry playground?
- When will MS Agent Framework GA? (question for Microsoft)

## What's Left

- Create Azure TAC memory adapter and use here (instead of rolling our own format memory context), should do the same for strands
- Public interface for voice conversation state (currently accesses TAC private `_conversations` — request a public getter from TAC)
- Test suite, linting/typing config
