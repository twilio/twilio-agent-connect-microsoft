# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

TAC Microsoft is an open-source library providing Azure-specific integrations for Twilio Agent Connect (TAC). It contains connectors that combine agent runtime integration with multi-channel conversation management.

**Key Architecture**: TAC Microsoft is a separate package that depends on TAC (Core Python) as an external dependency. It does NOT contain TAC source code — it imports from the `tac` package.

## Understanding TAC and Twilio Platform Services

TAC (Twilio Agent Connect) is middleware that integrates with several Twilio platform services to enable context-aware AI agents. Understanding these services is essential for using TAC Microsoft effectively.

### Conversation Orchestrator

**What it is**: Conversation Orchestrator organizes your voice calls, SMS messages, and WhatsApp messages into conversations. It observes traffic from your Twilio account, links it to customer profiles, and makes it available for AI agents and analytics.

**How TAC uses it**: TAC initializes a `ConversationClient` that interacts with Conversation Orchestrator APIs to:
- Create and manage conversations
- Track participants across channels
- List conversation history (communications)
- Link channel IDs (call IDs, message IDs) to conversations
- Retrieve conversation configuration (including memory store ID)

**In TAC Microsoft**: Connectors use TAC's conversation management to route messages to the appropriate agent instance per conversation. The `conversation_id` from Orchestrator becomes the session identifier for Azure agent runtimes (Agent Framework `AgentSession`, Voice Live WebSocket session).

### Conversation Memory

**What it is**: Conversation Memory provides agents with real-time, contextual data about customers. It stores and retrieves key facts, conversation history, preferences, and insights across different channels. This allows agents to build on previous conversations rather than treating every interaction as isolated.

**Key capabilities**:
- **Observations**: Facts and preferences extracted from conversations (e.g., "prefers window seats", "allergic to peanuts")
- **Summaries**: Conversation summaries that provide quick context
- **Sessions**: Historical session data
- **Profile lookup**: Find customer profiles by phone/email

**How TAC uses it**: TAC initializes a `MemoryClient` (using the memory_store_id from Conversation Orchestrator configuration) that:
- Retrieves memories via `retrieve_memory()` with optional semantic search
- Looks up profiles by phone/email when profile_id isn't available
- Provides memory context to your agent callback via `TACMemoryResponse`
- Falls back to Conversation Orchestrator's communication history if Memory API fails

**In TAC Microsoft**: Memory context is auto-retrieved per message and injected into the user message via `format_memory_context()` or a custom `on_message` hook. `memory_mode` on `SMSChannelConfig` / `ChatChannelConfig` / `VoiceChannelConfig` (`"always"` | `"never"` | `"once"`, default `"never"`) toggles this behavior.

### Conversation Intelligence

**What it is**: Conversation Intelligence analyzes conversations using language operators to extract insights, detect sentiment, generate summaries, and more. It processes conversations asynchronously and sends results via webhooks.

**How TAC uses it**: TAC includes an `OperatorResultProcessor` that:
- Processes Conversation Intelligence webhook events
- Filters events by configuration ID and operator SID
- Automatically creates observations or summaries in Conversation Memory based on CI results
- Handles multiple operator results per event

**In TAC Microsoft**: `TACFastAPIServer` provides an optional `/ci-webhook` endpoint for receiving Conversation Intelligence events. Connectors don't directly interact with CI, but they benefit from the observations and summaries that CI writes back into Memory.

### Knowledge

**What it is**: Knowledge provides semantic search capabilities over knowledge bases (FAQs, product documentation, company policies, etc.). It enables agents to ground responses in authoritative source material.

**How TAC uses it**: TAC optionally initializes a `KnowledgeClient` that:
- Searches knowledge bases with semantic queries
- Returns relevant chunks with relevance scores
- Provides a `create_knowledge_tool()` for LLM function calling

**In TAC Microsoft**: Knowledge search is exposed via `create_knowledge_tool()` in both `agent_framework_tools` (plain async callable) and `voice_live_tools` (`TACTool` instance). Knowledge results can supplement agent context alongside memory.

### How It All Works Together

1. **Conversation starts**: Customer sends SMS or calls → Conversation Orchestrator creates a conversation
2. **TAC retrieves context**: TAC uses conversation_id and profile_id to fetch memories from Conversation Memory
3. **Memory is injected**: TAC provides memory context to your agent (via callback or `format_memory_context()`)
4. **Agent responds**: Your agent (Agent Framework, Voice Live, etc.) processes user message with full context
5. **Conversation continues**: Subsequent messages in the same conversation maintain context
6. **Intelligence analyzes**: Conversation Intelligence processes the conversation and creates new observations/summaries
7. **Memory grows**: Future conversations benefit from richer customer profiles

## Development Commands

```bash
make sync              # Install dependencies (uses uv)
make dev-setup         # Full dev setup
make format            # Format with ruff
make lint              # Lint check only
make type-check        # mypy strict mode
make test              # Run pytest
make check             # All checks (lint + type-check + test)
```

## Package Structure

```
src/tac_microsoft/
├── __init__.py                         # Lazy-loaded public exports + re-exports from `tac`
├── agent_framework_connector.py        # AgentFrameworkConnector (voice + SMS + chat)
├── agent_framework_tools.py            # Tool factories returning plain async callables
├── agent_framework_types.py            # AgentSessionStore protocol
├── voice_live_connector.py             # VoiceLiveConnector (voice only)
├── voice_live_session.py               # Voice Live WebSocket session wrapper
├── voice_live_tools.py                 # Tool factories returning TACTool instances
├── voice_live_types.py                 # VoiceLiveConfig, VoiceLiveError
├── _tool_factories.py                  # Internal — shared tool logic (delegates to tac.tools)
├── utils.py                            # format_memory_context()
└── stores/                             # AgentSessionStore implementations
    ├── in_memory.py                    # InMemoryAgentSessionStore (default, single-instance)
    ├── file.py                         # FileAgentSessionStore (JSON on disk)
    └── cosmos.py                       # CosmosDBAgentSessionStore (horizontal scaling)

getting_started/
└── examples/
    ├── agent_framework/basic.py        # Minimal setup with OpenAIChatClient (Azure)
    ├── agent_framework/advanced.py     # Full features: channel-aware prompts, tools, hooks, session store
    └── voice_live/basic.py             # Voice Live with custom @function_tool

deploy/
├── agent_framework_container_apps/     # Agent Framework on Azure Container Apps (Bicep + azd)
└── voice_live_container_apps/          # Voice Live on Azure Container Apps (Bicep + azd)

tests/                                  # pytest suite (native asyncio mode)
```

## Code Conventions

- **Python 3.10+**: Prefer modern syntax (`str | None`, `list[str]`), `from __future__ import annotations` in new modules.
- **mypy strict**: All functions need type hints, no incomplete defs.
- **ruff**: Line length 100, isort-compatible import ordering.
- **Imports from TAC**: Always import from `tac` package, never from internal `tac_microsoft` paths except for local imports.
- **Lazy imports**: `tac_microsoft.__init__` uses `__getattr__` to lazy-load optional-extra modules so `import tac_microsoft` succeeds with just core deps installed.

## Dependencies

### Core Dependency

TAC Microsoft depends on TAC published on PyPI:

```toml
dependencies = [
    "twilio-agent-connect>=1.0.0,<2",
]
```

### Optional Extras

- `server` — TAC FastAPI server (pulls `tac[server]`)
- `agent-framework` — Microsoft Agent Framework + Azure AI + azure-identity
- `voice-live` — websockets client for Azure AI Foundry Voice Live
- `cosmos` — Azure Cosmos DB client for `CosmosDBAgentSessionStore`
- `dev` — All of the above plus ruff, mypy

## Key Concepts

### Connectors

Connectors combine agent runtime integration with multi-channel conversation management. They:
- Create and manage per-conversation agent instances
- Create Voice, SMS, and Chat channel instances (`VoiceChannel`, `SMSChannel`, `ChatChannel` from core TAC)
- Persist `AgentSession` via a pluggable `AgentSessionStore`
- Route responses to the right channel based on `context.channel`
- Register with TAC via `on_message_ready()`, `on_conversation_ended()`, `on_interrupt()` callbacks

**Available Connectors:**

**AgentFrameworkConnector** — Microsoft Agent Framework integration:
- Accepts `tac`, `create_agent: (ConversationSession) -> Agent`, optional hooks (`on_message`, `on_error`), optional channel configs, optional `session_store`.
- Voice: agent + `AgentSession` cached in-memory for the call duration; streamed responses; background save to `AgentSessionStore` after each utterance.
- SMS / Chat: load `AgentSession` from store → `agent.run()` → save back. Preserves Foundry `thread_id` and Responses API history across messages.
- Channels exposed as `voice_channel` / `sms_channel` / `chat_channel`.

**VoiceLiveConnector** — Azure AI Foundry Voice Live integration:
- Voice only (server-side conversation state; no `AgentSession` needed).
- One `VoiceLiveSession` per conversation; WebSocket managed internally.
- Tool execution via Azure-side function-calling protocol.

### Session Stores

`AgentSessionStore` is a Protocol (`load` / `save` / `delete`). Three implementations ship:

- `InMemoryAgentSessionStore` — default, single-instance only.
- `FileAgentSessionStore` — JSON on disk, good for local dev.
- `CosmosDBAgentSessionStore` — Azure Cosmos DB for NoSQL; suitable for horizontally-scaled production (lazy-init, auto-creates DB + container, TTL supported).

Custom implementations (Redis, DynamoDB, Postgres, etc.) just need to satisfy the protocol.

### Tools

Three built-in tool factories, all thin wrappers around core `tac.tools`:

- `create_memory_tool(tac, session, *, name=None, description=None)` — semantic memory search, scoped to the current profile.
- `create_knowledge_tool(tac, knowledge_base_id, *, name=None, description=None, top_k=5)` — **async** (core fetches KB metadata for defaults when `name`/`description` are omitted).
- `create_handoff_tool(tac, session, attributes=None)` — Studio-Flow handoff; requires `TWILIO_STUDIO_HANDOFF_FLOW_SID`.

Two export variants:
- `tac_microsoft.agent_framework_tools` — returns plain async callables (Agent Framework auto-discovers from function name/docstring/annotations).
- `tac_microsoft.voice_live_tools` — returns `TACTool` instances (Voice Live accepts them via `VoiceLiveConfig.tools`).

### Server

TAC Microsoft uses `TACFastAPIServer` from the core TAC package (`tac.server`). Connectors expose the channel instances; the server does the HTTP routing:

```python
server = TACFastAPIServer(
    tac=tac,
    voice_channel=connector.voice_channel,
    messaging_channels=[connector.sms_channel, connector.chat_channel],
)
```

## Import Patterns

### Correct Imports

```python
# TAC imports — external dependency
from tac import TAC, TACConfig
from tac.models.session import ConversationSession

# TAC Microsoft imports — local package (re-exports TAC core where possible)
from tac_microsoft import (
    AgentFrameworkConnector,
    VoiceLiveConnector,
    TACFastAPIServer,
    FileAgentSessionStore,
)
from tac_microsoft.agent_framework_tools import create_memory_tool, create_knowledge_tool
```

### Incorrect Imports (DO NOT DO)

```python
# ❌ Wrong - tac_microsoft has no `.core` submodule
from tac_microsoft.core import TAC

# ❌ Wrong - don't import from source paths
from src.tac.adapters import BaseAgentAdapter
```

## Example Usage Patterns

### Agent Framework with TAC Server

```python
from agent_framework.openai import OpenAIChatClient
from tac_microsoft import (
    TAC, TACConfig, TACFastAPIServer,
    AgentFrameworkConnector, ConversationSession,
    SMSChannelConfig,
)

tac = TAC(config=TACConfig.from_env())

client = OpenAIChatClient(
    azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
    api_key=os.environ["AZURE_AI_API_KEY"],
    model=os.environ["AZURE_AI_DEPLOYMENT_NAME"],
)

def create_agent(session: ConversationSession):
    return client.as_agent(name="MyAgent", instructions="You are helpful.")

connector = AgentFrameworkConnector(
    tac=tac,
    create_agent=create_agent,
    sms_config=SMSChannelConfig(memory_mode="always"),
)

server = TACFastAPIServer(
    tac=tac,
    voice_channel=connector.voice_channel,
    messaging_channels=[connector.sms_channel],
)
server.start()
```

### Horizontal Scaling with CosmosDBAgentSessionStore

```python
from tac_microsoft import CosmosDBAgentSessionStore

session_store = CosmosDBAgentSessionStore(
    endpoint=os.environ["AZURE_COSMOS_ENDPOINT"],
    credential=DefaultAzureCredential(),  # or a key string
)

connector = AgentFrameworkConnector(
    tac=tac,
    create_agent=create_agent,
    session_store=session_store,
)
```

### Voice Live with Custom Tools

```python
from tac.tools.base import function_tool
from tac_microsoft import TAC, TACConfig, TACFastAPIServer, VoiceLiveConnector, VoiceLiveConfig

tac = TAC(config=TACConfig.from_env())

@function_tool()
def look_up_outage(zip_code: str) -> str:
    """Check for recent outages in a zip code."""
    return f"No reported outages in {zip_code}."

config = VoiceLiveConfig(
    endpoint=os.environ["AZURE_VOICE_LIVE_ENDPOINT"],
    api_key=os.environ["AZURE_VOICE_LIVE_API_KEY"],
    instructions="You are a helpful assistant.",
    tools=[look_up_outage],
)

connector = VoiceLiveConnector(tac=tac, config=config)
server = TACFastAPIServer(tac=tac, voice_channel=connector.voice_channel)
server.start()
```

## Testing

Tests live in `tests/` and use pytest with `asyncio_mode = auto` (via `pytest.ini`). Run with `make test` or `uv run pytest`. Conventions:

- Import from `tac_microsoft` (local) and `tac` (external).
- Use `AsyncMock` / `MagicMock` for `TAC`, channels, and Azure clients.
- Treat the tool factories as thin wrappers around `tac.tools` — prefer testing the wiring, not reimplementing core's tests.

## Updating TAC Dependency

When a new `twilio-agent-connect` version is released on PyPI, bump the version constraint in `pyproject.toml` (all three entries — base, server extra, dev extra) and re-sync:

```bash
uv sync --all-extras
make check
```

## Common Pitfalls

1. **Don't import TAC classes from `tac_microsoft` internal paths** — use `from tac.X import Y`.
2. **Don't copy TAC source code** — TAC is a pinned git dependency, not vendored.
3. **Connectors own the channels** — don't instantiate `VoiceChannel` / `SMSChannel` / `ChatChannel` yourself; read them off the connector.
4. **`create_knowledge_tool` is async** — if you call it inside a sync `create_agent` factory, build it once at module load via `asyncio.run()` and reuse the result.
5. **Lazy `__getattr__`** — if you add a new top-level export, update both the `__getattr__` branch and `__all__` in `src/tac_microsoft/__init__.py`.

## Related Documentation

- TAC Core: [CLAUDE.md](https://github.com/twilio/twilio-agent-connect-python/blob/main/CLAUDE.md)
- TAC AWS sibling: [CLAUDE.md](https://github.com/twilio/aws-twilio-agent-connect-python/blob/main/CLAUDE.md)
- Microsoft Agent Framework: [github.com/microsoft/agent-framework](https://github.com/microsoft/agent-framework)
- Azure AI Foundry Voice Live: [learn.microsoft.com/azure/ai-foundry](https://learn.microsoft.com/azure/ai-foundry/)
