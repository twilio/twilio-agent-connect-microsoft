# tac-azure — What's Different vs Strands SDK

## Net-New Features

- **Webhook signature validation** — built-in, on by default
- **Memory auto-injection** — fetched memory auto-prepended to prompts. Opt out of fetching (`auto_retrieve_memory=False`) or customize formatting (`on_message` hook)
- **Multi-provider support** — Azure OpenAI, Foundry, OpenAI, Anthropic, Bedrock, Ollama, GitHub Copilot, etc. via MS Agent Framework
- **`SessionStore` protocol** — pluggable persistence (default: in-memory; swap for Redis, CosmosDB, etc.)
- **Incremental voice session persistence** — background-saves after each utterance for auditing without impacting latency
- **Channel selection** — `channels=["voice"]` or `channels=["sms"]` to init only what you need
- **Foundry UI → Twilio** — define agents in Azure Foundry portal, then use them with Twilio via the SDK

## Simplified Agent Interface

- Replaces `AgentProxy` ABC (3 methods, 2 classes) — uses `agent_framework.Agent` directly
- Factory receives full `ConversationSession` instead of two strings — enables channel-aware agents
- Streaming uses `chunk.text` instead of deep dict traversal

## Cleaner Handler/Server Split

- `OmniChannelServer` is a thin wrapper over `OmniChannelHandler` — no duplicated logic (Strands duplicates significantly)
- `on_startup` hook for async init (e.g., knowledge base metadata fetch)

## Tool Registration

- No `@tool` decorator needed — Agent Framework auto-discovers from function name + docstring + types
- Knowledge tool split into sync `create_knowledge_tool()` + async `fetch_knowledge_base_info()` helper

## Newer TAC + Managed SMS Lifecycle

Partly enabled by a **newer TAC pin** (unified `on_message_ready` for voice+SMS, `auto_retrieve_memory` flag, `idempotency_token`). Strands gets these once its TAC pin is bumped.

On top of that, the Azure SDK:
- Registers the callback internally — no manual `on_message_ready` wiring
- Unified voice/SMS dispatch through one code path
- Auto loads/saves session around `agent.run()` for cross-message continuity

## Not Yet in Azure

- No test suite (Strands has pytest + fixtures + testing guide)
- No linting/typing config (Strands has ruff + mypy)
- No RFC/implementation plan docs
