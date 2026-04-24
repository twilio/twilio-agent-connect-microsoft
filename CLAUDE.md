# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

TAC Azure is an open-source library providing Azure-specific integrations for Twilio Agent Connect (TAC). It contains connectors that combine agent runtime integration with multi-channel conversation management.

**Key Architecture**: TAC Azure is a separate package that depends on TAC (Core Python) as an external dependency. It does NOT contain TAC source code — it imports from the `tac` package.

## Understanding TAC and Twilio Platform Services

TAC (Twilio Agent Connect) is middleware that integrates with several Twilio platform services (Conversation Orchestrator, Conversation Memory, Conversation Intelligence, Knowledge) to enable context-aware AI agents.

For a full rundown of how each Twilio service works and how TAC plugs into them, see the [TAC AWS CLAUDE.md](https://github.com/twilio-innovation/aws-twilio-agent-connect-python/blob/main/CLAUDE.md#understanding-tac-and-twilio-platform-services) — it's the same platform, just with AWS connectors swapped for Azure ones.

### How TAC Azure uses Twilio services

- **Conversation Orchestrator** — routes messages/calls to `AgentFrameworkConnector` or `VoiceLiveConnector`; `conversation_id` becomes the session identifier for the Azure agent runtime (Agent Framework `AgentSession`, Voice Live WebSocket session).
- **Conversation Memory** — auto-retrieved via `MemoryClient`; memory context is injected into the user message through `format_memory_context()` or a custom `on_message` hook. `auto_retrieve_memory` on `SMSChannelConfig` / `ChatChannelConfig` / `VoiceChannelConfig` toggles this.
- **Conversation Intelligence** — not directly invoked by connectors; benefits show up automatically as the CI pipeline writes observations/summaries back into Memory.
- **Knowledge** — exposed via `create_knowledge_tool()` in both `agent_framework_tools` and `voice_live_tools`.

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
src/tac_azure/
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
    ├── agent_framework/basic.py        # Minimal setup with AzureOpenAIResponsesClient
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
- **Imports from TAC**: Always import from `tac` package, never from internal `tac_azure` paths except for local imports.
- **Lazy imports**: `tac_azure.__init__` uses `__getattr__` to lazy-load optional-extra modules so `import tac_azure` succeeds with just core deps installed.

## Dependencies

### Core Dependency

TAC Azure depends on TAC from GitHub (locked to a specific commit):

```toml
dependencies = [
    "twilio-agent-connect @ git+https://github.com/twilio-innovation/twilio-agent-connect-python.git@{commit_hash}",
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
- `tac_azure.agent_framework_tools` — returns plain async callables (Agent Framework auto-discovers from function name/docstring/annotations).
- `tac_azure.voice_live_tools` — returns `TACTool` instances (Voice Live accepts them via `VoiceLiveConfig.tools`).

### Server

TAC Azure uses `TACFastAPIServer` from the core TAC package (`tac.server`). Connectors expose the channel instances; the server does the HTTP routing:

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

# TAC Azure imports — local package (re-exports TAC core where possible)
from tac_azure import (
    AgentFrameworkConnector,
    VoiceLiveConnector,
    TACFastAPIServer,
    FileAgentSessionStore,
)
from tac_azure.agent_framework_tools import create_memory_tool, create_knowledge_tool
```

### Incorrect Imports (DO NOT DO)

```python
# ❌ Wrong - tac_azure has no `.core` submodule
from tac_azure.core import TAC

# ❌ Wrong - don't import from source paths
from src.tac.adapters import BaseAgentAdapter
```

## Example Usage Patterns

### Agent Framework with TAC Server

```python
from agent_framework.azure import AzureOpenAIResponsesClient
from tac_azure import (
    TAC, TACConfig, TACFastAPIServer,
    AgentFrameworkConnector, ConversationSession,
    SMSChannelConfig,
)

tac = TAC(config=TACConfig.from_env())

client = AzureOpenAIResponsesClient(
    endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
    api_key=os.environ["AZURE_AI_API_KEY"],
    deployment_name=os.environ["AZURE_AI_DEPLOYMENT_NAME"],
)

def create_agent(session: ConversationSession):
    return client.as_agent(name="MyAgent", instructions="You are helpful.")

connector = AgentFrameworkConnector(
    tac=tac,
    create_agent=create_agent,
    sms_config=SMSChannelConfig(auto_retrieve_memory=True),
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
from tac_azure import CosmosDBAgentSessionStore

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
from tac_azure import TAC, TACConfig, TACFastAPIServer, VoiceLiveConnector, VoiceLiveConfig

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

- Import from `tac_azure` (local) and `tac` (external).
- Use `AsyncMock` / `MagicMock` for `TAC`, channels, and Azure clients.
- Treat the tool factories as thin wrappers around `tac.tools` — prefer testing the wiring, not reimplementing core's tests.

## Updating TAC Dependency

When TAC core has new changes, update the commit hash in `pyproject.toml`:

```bash
# In TAC core repo
git rev-parse HEAD

# In this repo
# Update pyproject.toml with new commit hash (all three entries — base, server extra, dev extra)
# Then:
uv sync --all-extras
make check
```

## Common Pitfalls

1. **Don't import TAC classes from `tac_azure` internal paths** — use `from tac.X import Y`.
2. **Don't copy TAC source code** — TAC is a pinned git dependency, not vendored.
3. **Connectors own the channels** — don't instantiate `VoiceChannel` / `SMSChannel` / `ChatChannel` yourself; read them off the connector.
4. **`create_knowledge_tool` is async** — if you call it inside a sync `create_agent` factory, build it once at module load via `asyncio.run()` and reuse the result.
5. **Lazy `__getattr__`** — if you add a new top-level export, update both the `__getattr__` branch and `__all__` in `src/tac_azure/__init__.py`.

## Related Documentation

- TAC Core: [CLAUDE.md](https://github.com/twilio-innovation/twilio-agent-connect-python/blob/main/CLAUDE.md)
- TAC AWS sibling: [CLAUDE.md](https://github.com/twilio-innovation/aws-twilio-agent-connect-python/blob/main/CLAUDE.md)
- Microsoft Agent Framework: [github.com/microsoft/agent-framework](https://github.com/microsoft/agent-framework)
- Azure AI Foundry Voice Live: [learn.microsoft.com/azure/ai-foundry](https://learn.microsoft.com/azure/ai-foundry/)
