# tac-azure — Architecture Review

## What is this?

A Python SDK for building Twilio voice + SMS agents using **Microsoft Agent Framework** (successor to Semantic Kernel, currently in RC).

Same role as `strands-communications-twilio` but for the Azure/Microsoft ecosystem.

## Why Microsoft Agent Framework?

- **Multi-provider** — Azure OpenAI, Foundry Agent Service, OpenAI, Anthropic, Ollama, GitHub Copilot, Copilot Studio, custom ([full list](https://learn.microsoft.com/en-us/agent-framework/agents/providers/?pivots=programming-language-python))
- **Foundry UI** — define agents in Azure Foundry portal, reference by ID via `agent_id` param, use with Twilio via the SDK ([docs](https://learn.microsoft.com/en-us/agent-framework/agents/providers/azure-ai-foundry?pivots=programming-language-python))
- **Generic `Agent` type** — SDK code is not tied to Azure; only the examples use Azure clients
- **Stable API** — In preview, but in Release Candidate status, API surface is frozen: https://devblogs.microsoft.com/foundry/microsoft-agent-framework-reaches-release-candidate/
- **Auto tool discovery** — no `@tool` decorator needed; uses function name + docstring + type annotations

## SDK Design

Three layers — customer code on top, shared TAC foundation on the bottom:

```
┌─────────────────────────────────────────────────┐
│  Customer code                                  │
│  • create_agent(session) -> Agent               │
│  • System prompts, custom tools                 │
└──────────────────────┬──────────────────────────┘
                       │ uses
┌──────────────────────▼──────────────────────────┐
│  OmniChannelServer (batteries-included)         │
│  • Pre-wired FastAPI routes                     │
│  • Webhook signature validation                 │
│  • on_startup hook                              │
└──────────────────────┬──────────────────────────┘
                       │ delegates to
┌──────────────────────▼──────────────────────────┐
│  OmniChannelHandler (core logic)                │
│  • Agent lifecycle (voice + SMS)                │
│  • SessionStore (pluggable persistence)         │
│  • Memory auto-injection, on_message hook       │
│  • Tool wrappers (thin — delegate down to TAC)  │
└──────────────────────┬──────────────────────────┘
                       │ delegates to
┌──────────────────────▼──────────────────────────┐
│  TAC (shared with Strands SDK)                  │
│  • VoiceChannel, SMSChannel                     │
│  • MemoryClient, KnowledgeClient                │
│  • TACTool system, webhook signature validation │
└─────────────────────────────────────────────────┘
```

Customer code can use OmniChannelServer directly, or use OmniChannelHandler with their own FastAPI app for full control over routing and middleware.

This SDK is a thin orchestration layer. Tool logic and webhook validation live in TAC — not reimplemented here.

## What's New vs Strands

See [DIFFERENCES_VS_STRANDS.md](./DIFFERENCES_VS_STRANDS.md) for the full comparison.

Some features are partly enabled by a **newer TAC pin** (unified `on_message_ready` for voice+SMS, `auto_retrieve_memory` flag, `idempotency_token`). Strands gets these once its TAC pin is bumped.

## Key Design Decisions

| Decision                       | Rationale                                                                                                         |
| ------------------------------ | ----------------------------------------------------------------------------------------------------------------- |
| Use `Agent` type directly      | Already depends on agent_framework; custom protocol adds complexity without value                                 |
| `SessionStore` interface       | Decouples persistence from handler; enables Redis/CosmosDB without code changes                                   |
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
