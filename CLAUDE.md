# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Keep it accurate: when a change alters anything described here (behavior, commands, layout, CI), update this file in the same PR.

If a PR, including later pushes to it, conflicts with anything in this file, the PR must also update this file to match before it merges.

## Project Overview

twilio-agent-connect-microsoft is an open-source library providing Azure integrations for Twilio Agent Connect (TAC). It contains connectors that combine an Azure agent runtime integration with multi-channel conversation management.

**Key Architecture**: twilio-agent-connect-microsoft is a separate package that depends on TAC (core Python) as an external dependency. It does NOT contain TAC source code — it imports from the `tac` package.

## Understanding TAC

TAC (Twilio Agent Connect) is middleware that integrates with Twilio platform services:
- **Conversation Orchestrator** - Organizes voice/SMS/WhatsApp into conversations
- **Conversation Memory** - Stores customer context, preferences, and history
- **Conversation Intelligence** - Extracts insights via language operators
- **Knowledge** - Semantic search over knowledge bases

**In twilio-agent-connect-microsoft**: Connectors register `on_message_ready()`, `on_conversation_ended()` and `on_interrupt()` callbacks on a `TAC` instance, inject Conversation Memory into the user message (`format_memory_context()` or a custom `on_message` hook, toggled per channel by `memory_mode`: `"always"` | `"never"` | `"once"`, default `"never"`), and route each reply back on the channel it arrived on. The TAC conversation id is the key for per-conversation agent state (an Agent Framework `AgentSession`, a Voice Live WebSocket session). Knowledge is exposed through `create_knowledge_tool()`, and Conversation Intelligence results reach agents only through the observations and summaries CI writes back into Memory (via `TACFastAPIServer`'s optional `/ci-webhook`).

## Development Commands

```bash
make sync              # Install dependencies (uv sync --all-extras)
make dev-setup         # Full dev setup (sync only; no pre-commit hooks)
make format            # Format with ruff
make lint              # Lint check only
make type-check        # mypy (disallow_untyped_defs)
make test              # Run pytest
make check             # All checks (lint + type-check + test)
make docs              # Build the docs site into site/ (--strict, fails on broken links)
make docs-serve        # Serve docs locally with live reload
make docs-versions     # List versioned docs published to gh-pages
```

Lint and format run ruff over the whole repo; mypy covers `src/tac_microsoft`, `getting_started` and `deploy`; pytest covers `tests/`.

## Package Structure

```
src/tac_microsoft/
├── __init__.py                         # Lazy-loaded public exports + re-exports from `tac`
├── agent_framework_connector.py        # AgentFrameworkConnector (voice + SMS + chat + RCS + WhatsApp)
├── agent_framework_tools.py            # Tool factories returning plain async callables
├── agent_framework_types.py            # AgentSessionStore protocol
├── hosted_agents_server.py             # TACHostedAgentsApp (Hosted Agents in Foundry Agent Service)
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
├── agent_framework_hosted_agents/      # Agent Framework on Hosted Agents in Foundry Agent Service (APIM + Bicep + azd)
└── voice_live_container_apps/          # Voice Live on Azure Container Apps (Bicep + azd)

tests/                                  # pytest suite (native asyncio mode)
```

## Code Conventions

- **Python 3.10+**: `requires-python` is `>=3.10`. Use modern syntax (`str | None`, `list[str]`) with `from __future__ import annotations`.
- **mypy**: `disallow_untyped_defs` and `disallow_incomplete_defs` are on, so every function needs full type hints. The `pydantic.mypy` plugin is enabled to match core TAC.
- **ruff**: Line length 100, rule sets `E W F I B C4 UP N`, isort ordering with `tac_microsoft` as first-party.
- **Imports from TAC**: Always import from the `tac` package; never import TAC classes from internal `tac_microsoft` paths.
- **Lazy imports**: `tac_microsoft.__init__` uses `__getattr__` to lazy-load optional-extra modules so `import tac_microsoft` succeeds with just core deps installed.

## Dependencies

### Core Dependency

```toml
dependencies = [
    "twilio-agent-connect>=2.1.0,<3",
]
```

### Optional Extras

Each runtime's Azure SDK is only required by its own extra, so installing with no extras never fails on import.

- `server` — TAC FastAPI server (pulls `tac[server]`)
- `agent-framework` — Microsoft Agent Framework + Azure AI + azure-identity
- `voice-live` — websockets client for Azure AI Foundry Voice Live
- `cosmos` — Azure Cosmos DB client for `CosmosDBAgentSessionStore`
- `hosted-agents` — Hosted Agents in Foundry Agent Service server (`TACHostedAgentsApp`). Pulls `azure-ai-agentserver-invocations` and `azure-ai-agentserver-core` (both pre-release betas as of writing) from PyPI.
- `dev` — All of the above plus pytest, ruff and mypy
- `docs` is a dependency group (`uv run --group docs ...`), not an extra

## Key Concepts

### Connectors

Connectors combine agent runtime integration with channel management. Each one:
- Builds the channel set: Voice always; `AgentFrameworkConnector` adds SMS and Chat always, plus RCS and WhatsApp only when `TWILIO_RCS_SENDER_ID` / `TWILIO_WHATSAPP_NUMBER` is configured. Their `*_config` args are tuning only and never enable a channel.
- Exposes channels as attributes (`voice_channel`, `sms_channel`, `chat_channel`, and `rcs_channel` / `whatsapp_channel`, which are `None` when not configured).
- Registers with TAC via `on_message_ready()`, `on_conversation_ended()` and `on_interrupt()`.
- Injects Conversation Memory into the user message per the channel's `memory_mode`.

**AgentFrameworkConnector**: Microsoft Agent Framework integration. Accepts `tac`, `create_agent: (ConversationSession) -> Agent`, optional hooks (`on_message`, `on_error`), optional channel configs and an optional `session_store`. Voice caches the agent and `AgentSession` in memory for the call, streams responses, and saves to the `AgentSessionStore` in the background after each utterance. SMS / Chat / RCS / WhatsApp share one messaging handler: load `AgentSession` from the store, `agent.run()`, save back, preserving Foundry `thread_id` and Responses API history across messages.

**VoiceLiveConnector**: Azure AI Foundry Voice Live integration. Voice only, with server-side conversation state (no `AgentSession`). One `VoiceLiveSession` per conversation with the WebSocket managed internally; tools run over the Azure-side function-calling protocol.

### Voice / TwiML customization, relay-only, and outbound

The connector owns the `VoiceChannel`, so these voice features are used directly on it — nothing extra to wire:

- **Per-call TwiML customization**: `connector.voice_channel.on_inbound_call_twiml(cb)` where `async cb(req: TwiMLRequest) -> TwiMLOptions`. Fields the callback sets override `VoiceChannelConfig.default_twiml_options` and TAC defaults; unset fields fall through. `TwiMLRequest` / `TwiMLOptions` are re-exported from `tac_microsoft`.
- **Welcome greeting**: set it via `VoiceChannelConfig(default_twiml_options=TwiMLOptions(welcome_greeting=...))`; the channel supplies a default when unset.
- **ConversationRelay-only voice** (no Orchestrator): leave `TWILIO_CONVERSATION_CONFIGURATION_ID` unset — core TAC gates orchestrated vs relay-only behavior on it.
- **Outbound initiation**: `InitiateVoiceConversationOptions` / `InitiateMessagingConversationOptions` / `InitiateChatConversationOptions` and their result types are re-exported from `tac_microsoft`.

> **Config note:** voice URL fields live on `TACConfig` (`voice_public_domain` / `voice_websocket_path` / `voice_action_path`); `TACHostedAgentsApp` reads them from `tac.config`.

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

twilio-agent-connect-microsoft ships two server classes that both plug into the same connector channels:

- **`TACFastAPIServer`** (re-exported from `tac.server`) — FastAPI/uvicorn, runs on Container Apps or any general HTTP host. Five routes: `/webhook`, `/twiml`, `/ws`, `/conversation-relay-callback`, optional `/ci-webhook`.
- **`TACHostedAgentsApp`** (`tac_microsoft.hosted_agents_server`) — wraps `InvocationAgentServerHost` for the Hosted Agents in Foundry Agent Service runtime. Hosted Agents only exposes `POST /invocations` and `WS /invocations_ws`, so this server overloads the HTTP route and dispatches by payload shape (Conversation Orchestrator JSON envelope vs. Twilio voice TwiML form). APIM in front handles HMAC validation (the only auth boundary — agent does not re-validate `X-Twilio-Signature`), form→JSON conversion, and `agent_session_id` injection.

```python
# Container Apps / general HTTP
server = TACFastAPIServer(
    tac=tac,
    voice_channel=connector.voice_channel,
    messaging_channels=[connector.sms_channel, connector.chat_channel],
)

# Hosted Agents in Foundry Agent Service
server = TACHostedAgentsApp(
    tac=tac,
    voice_channel=connector.voice_channel,
    messaging_channels=[connector.sms_channel],
)
```

## Import Patterns

### Correct Imports

```python
# TAC imports - external dependency
from tac import TAC, TACConfig
from tac.models.session import ConversationSession

# twilio-agent-connect-microsoft imports - local package (re-exports TAC core where possible)
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

**See full examples**: `getting_started/examples/agent_framework/` (`basic.py`, `advanced.py`)

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

**See full examples**: `deploy/agent_framework_container_apps/`

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

**See full examples**: `getting_started/examples/voice_live/basic.py`

## Testing

Tests live in `tests/` and use pytest with `asyncio_mode = auto` (see `pytest.ini`). Run with `make test` or `uv run pytest`. Tests should:
- Import from `tac_microsoft` (local) and `tac` (external dependency)
- Mock `TAC`, channels and Azure clients with `AsyncMock` / `MagicMock` rather than calling Azure APIs
- Treat the tool factories as thin wrappers around `tac.tools`: test the wiring, not core's behavior

CI's `TAC Compat` matrix also runs lint, mypy and tests against the latest patch of each `twilio-agent-connect` minor in the `pyproject.toml` range (`.github/scripts/tac_versions.py`), so code must work on the oldest supported minor, not just the locked one. The matrix runs on Python 3.10, the oldest version this package supports. Reproduce and fix steps: CONTRIBUTING.md, "SDK Compatibility Checks".

## Updating TAC Dependency

When a new `twilio-agent-connect` release is published to PyPI, bump every `twilio-agent-connect` constraint in `pyproject.toml` together (base dependency and each extra that pulls it), then re-lock and run all checks:

```bash
make sync
make check
```

Raising the lower bound drops older minors from the `TAC Compat` matrix, so only raise it when code needs a newer TAC feature.

## Documentation

- The public API reference is published at https://twilio.github.io/twilio-agent-connect-microsoft/, versioned with `mike` and deployed from `.github/workflows/docs.yml` on each GitHub release.
- API docs are generated from docstrings by MkDocs Material + mkdocstrings, so **docstrings are published documentation**. Write them for both source readers and the rendered site.
- Use **Markdown** in docstrings: `**bold**`, `- ` bullet lists, backticks for identifiers, and fenced code blocks for examples, with a blank line before a list or fenced block.
- TAC core types (`TAC`, `ConversationSession`, ...) resolve to the TAC Python docs via the `inventories` entry in `mkdocs.yml`, so annotating with real TAC types produces cross-repo links.
- `docs/api/*.md` targets individual modules (e.g. `tac_microsoft.agent_framework_connector`), not the top-level `tac_microsoft` package: `src/tac_microsoft/__init__.py` resolves optional connectors/stores/server through `__getattr__` at runtime, which griffe can't resolve statically. When you add a new module, add it to the corresponding docs page directly.
- `docs/index.md` and `docs/deploy/**/README.md` are one-line snippet includes of `README.md` and the `deploy/*/README.md` guides. Edit the source Markdown, never the stub, and use absolute GitHub URLs for paths outside the mirrored `deploy/` tree (e.g. `getting_started/`) in those files.
- Verify docs changes with `make docs` (`uv run --group docs mkdocs build --strict`).

## Common Pitfalls

1. **Don't import TAC classes from internal `tac_microsoft` paths** - use `from tac.X import Y`, or the top-level `tac_microsoft` re-exports.
2. **Don't copy TAC source code** - TAC is a dependency, not vendored.
3. **Don't pass `None` channels to a server** - `connector.rcs_channel` and `connector.whatsapp_channel` are `None` when not configured.
4. **Connectors own the channels** - don't create separate channel instances for them.
5. **`create_knowledge_tool` is async** - if you call it inside a sync `create_agent` factory, build it once at module load via `asyncio.run()` and reuse the result.
6. **Lazy `__getattr__`** - if you add a new top-level export, update both the `__getattr__` branch and `__all__` in `src/tac_microsoft/__init__.py`.

## Related Documentation

- TAC Core: [twilio-agent-connect-python](https://github.com/twilio/twilio-agent-connect-python)
- TAC AWS sibling: [twilio-agent-connect-aws](https://github.com/twilio/twilio-agent-connect-aws)
- TAC Google sibling: [twilio-agent-connect-google](https://github.com/twilio/twilio-agent-connect-google)
- Microsoft Agent Framework: [github.com/microsoft/agent-framework](https://github.com/microsoft/agent-framework)
- Azure AI Foundry Voice Live: [learn.microsoft.com/azure/ai-foundry](https://learn.microsoft.com/azure/ai-foundry/)
- Examples: `getting_started/examples/`
- Deployment: `deploy/README.md`
- Published API reference: [twilio.github.io/twilio-agent-connect-microsoft](https://twilio.github.io/twilio-agent-connect-microsoft/)
