# TAC + Partner SDK Interface Design

## Overview

Three packages, clear ownership boundaries:

| Package | Repo | Python import | Source path |
|---|---|---|---|
| **TAC** | `twilio-agent-connect-python` | `tac` | `../twilio-agent-connect-python/` |
| **MS Agent Framework SDK** | `azure-twilio-agent-connect-python` | `tac_ms_agent_framework` (currently `tac_azure`) | `../azure-twilio-agent-connect-python/` |
| **Strands SDK** | `strands-communications-twilio` | `tac_strands` (currently `strands_communications`) | `../strands-communications-twilio/` |

- **TAC** — owns everything Twilio-specific: channels, routes, tools, session management, callbacks
- **Partner SDKs** — own the agent framework bridge and cloud runtime server

Both partner SDKs export the same three class names with the same shape. The only differences are framework-specific constructor parameters and internal agent logic.

```
┌────────────────────────────────────────────────────────────────┐
│  Interface 3: OmniChannelServer                                │
│  (Combined — creates both internally, one .start() call)       │
│                                                                │
│  ┌──────────────────────────┐  ┌───────────────────────────┐   │
│  │ Interface 1:             │  │ Interface 2:              │   │
│  │ AgentFrameworkBridge       │  │ RuntimeServer             │   │
│  │ (TAC + agent framework,  │  │ (Cloud runtime + TAC      │   │
│  │  deployment-agnostic)    │  │  routes)                  │   │
│  └──────────────────────────┘  └───────────────────────────┘   │
└────────────────────────────────────────────────────────────────┘
```

---

## The Three Interfaces

### Interface 1: `AgentFrameworkBridge`

TAC + agent framework bridge. Creates channels, wires callbacks, exposes routes. A pure request-processing object with no lifecycle of its own — agnostic to where it runs. Mount it on `TACServer`, `RuntimeServer`, or a custom ASGI app.

**Common shape (both SDKs):**

```python
class AgentFrameworkBridge:
    def __init__(
        self,
        tac: TAC,
        create_agent: Callable[[ConversationSession], AgentType],
        *,
        channels: list[str] | None = None,       # default: ["voice", "sms"]
        config: TACServerConfig | None = None,
        auto_retrieve_memory: bool = True,
        # framework-specific kwargs...
    ): ...

    # --- Public attributes ---
    tac: TAC
    voice_channel: VoiceChannel | None
    sms_channel: SMSChannel | None
    config: TACServerConfig
```

The handler does **not** create `TACRoutes`. Routes are an HTTP/server concern — they're created by the server layer (`RuntimeServer`, `TACServer`, or the developer) from the handler's channels. This matches how the current Azure `OmniChannelServer` already works: the handler exposes channels and methods, the server creates routes.

**What it does internally:**

```python
# Creates TAC primitives
self.voice_channel = VoiceChannel(tac, session_manager=ThreadSafeSessionManager(), ...)
self.sms_channel = SMSChannel(tac, ...)

# Wires SDK callbacks to TAC's callback system
tac.on_message_ready(self._handle_message)
tac.on_conversation_ended(self._handle_conversation_ended)
tac.on_interrupt(self._handle_interrupt)
```

**The three TAC callbacks and what the SDK does in each:**

| Callback | When TAC fires it | What the SDK handler does |
|---|---|---|
| `on_message_ready(user_message, context, memory)` | After a voice utterance or SMS message arrives (and optional memory retrieval completes) | Dispatches by `context.channel`: voice → `_stream_response()` via `voice_channel.send_response()`; SMS → create agent, run, send response, persist session |
| `on_conversation_ended(context)` | When a conversation is closed (voice WebSocket disconnect cleanup, SMS conversation closed via Maestro) | Voice: `_cleanup_voice_agent()` — pops cached agent/session, runs final cleanup (MS AF: background-save `AgentSession`; Strands: `agent.cleanup()`). SMS: optionally cleans up session store entry. |
| `on_interrupt(context, interrupt_data)` | When the user interrupts the agent mid-speech (voice only — `InterruptMessage` from ConversationRelay) | Cancels the in-flight agent streaming task. MS AF: the `AgentSession` retains any partial history from the interrupted run. Strands: `agent.stream_async()` generator is closed. Both: `SessionState.cancel_stream_task()` in TAC handles the actual task cancellation; the SDK callback is for agent-level cleanup if needed. |

**Why `on_interrupt` matters.** Without the interrupt callback wired, a user interrupting mid-sentence would leave the agent's streaming task running in the background, consuming resources and potentially sending stale tokens after the next utterance begins. TAC's `VoiceChannel` handles the WebSocket-level interrupt (cancelling `SessionState.stream_task`), but the SDK callback gives the handler a hook to perform framework-specific cleanup — e.g., aborting an in-flight LLM API call or rolling back partial tool execution.

**Microsoft Agent Framework-specific constructor params:**

```python
session_store: AgentSessionStore | None = None   # SMS conversation persistence
on_message: Callable[..., str] | None = None     # custom message augmentation hook
```

**Strands has no additional params currently.**

The `create_agent` factory takes `ConversationSession` in both SDKs, standardizing the current inconsistency (Strands currently takes `(conversation_id, profile_id)`). `ConversationSession` gives the factory access to `channel`, `profile`, `metadata` — not just IDs.

**Factory return type.** The factory returns a different type per SDK: `Agent` (MS Agent Framework) vs `AgentProxy` (Strands). `AgentFrameworkBridge` is not generic over this type — each SDK's concrete `AgentFrameworkBridge` class hardcodes the expected return type in its type annotations and internal methods (`_stream_response`, `_get_or_create_voice_agent`, etc.). The factory's return value is opaque to the common interface; it's only consumed by SDK-internal code that knows the concrete type. Type checkers validate within each SDK's module boundary. No shared `AgentProtocol` is needed because the two frameworks have fundamentally different agent APIs (`agent.run(stream=True)` vs `agent.stream_async()`) — a common protocol would be either too broad to be useful or too narrow to capture the differences.

---

### Interface 2: `RuntimeServer`

Mounts an `AgentFrameworkBridge`'s TAC routes onto a cloud runtime app.

**Common shape (both SDKs):**

```python
class RuntimeServer:
    def __init__(self, omnichannel: AgentFrameworkBridge, ...): ...

    app: StarletteApp  # the underlying ASGI app

    def start(self, **kwargs) -> None: ...
```

**ms-agent-framework-twilio-agent-connect-python — Foundry Agent Service:**

```python
class RuntimeServer:
    """Mounts TAC routes on FoundryCBAgent.

    Provides Foundry endpoints (POST /responses, /liveness, /readiness,
    conversation persistence, OpenTelemetry, OAuth) alongside TAC's
    Twilio endpoints.
    """

    def __init__(
        self,
        omnichannel: AgentFrameworkBridge,
        foundry_agent: FoundryCBAgent,
    ): ...
```

**strands-twilio-agent-connect-python — Bedrock AgentCore:**

```python
class RuntimeServer:
    """Mounts TAC routes on BedrockAgentCoreApp.

    Provides AgentCore endpoints (POST /invocations, /ping with
    HEALTHY/HEALTHY_BUSY, task tracking, request context) alongside
    TAC's Twilio endpoints.
    """

    def __init__(
        self,
        omnichannel: AgentFrameworkBridge,
        **agentcore_kwargs,
    ): ...
```

`RuntimeServer` contains zero TAC logic. It only knows how to mount Starlette routes (from TAC's `TACRoutes`) onto a cloud-specific Starlette app. The route handlers themselves live in TAC.

**Why a class instead of a factory function?** Although `RuntimeServer` is thin (~30 lines per SDK), it justifies being a class for three reasons: (1) cloud runtimes have their own lifecycle — `FoundryCBAgent` manages OAuth, OpenTelemetry, and liveness probes; `BedrockAgentCoreApp` manages `/ping` health with `HEALTHY`/`HEALTHY_BUSY` states and task tracking — and `RuntimeServer.start()` delegates to this lifecycle; (2) it exposes the underlying `.app` property, giving developers access to add middleware, custom routes, or startup hooks to the cloud-native app; (3) it makes `OmniChannelServer` a clean two-field composite (`self.omnichannel` + `self.runtime`) rather than inlining cloud-specific setup code.

---

### Interface 3: `OmniChannelServer`

Creates both `AgentFrameworkBridge` and `RuntimeServer` internally. Single constructor, single `.start()`.

**ms-agent-framework-twilio-agent-connect-python:**

```python
class OmniChannelServer:
    def __init__(
        self,
        tac: TAC,
        create_agent: Callable[[ConversationSession], Agent],
        foundry_agent: FoundryCBAgent,
        *,
        channels: list[str] | None = None,
        config: TACServerConfig | None = None,
        auto_retrieve_memory: bool = True,
        session_store: AgentSessionStore | None = None,
        on_message: Callable[..., str] | None = None,
    ):
        self.omnichannel = AgentFrameworkBridge(
            tac=tac, create_agent=create_agent, channels=channels,
            config=config, auto_retrieve_memory=auto_retrieve_memory,
            session_store=session_store, on_message=on_message,
        )
        self.runtime = RuntimeServer(
            omnichannel=self.omnichannel, foundry_agent=foundry_agent,
        )

    @property
    def app(self):
        return self.runtime.app

    def start(self, **kwargs):
        self.runtime.start(**kwargs)
```

**strands-twilio-agent-connect-python:**

```python
class OmniChannelServer:
    def __init__(
        self,
        tac: TAC,
        create_agent: Callable[[ConversationSession], AgentProxy],
        *,
        channels: list[str] | None = None,
        config: TACServerConfig | None = None,
        auto_retrieve_memory: bool = True,
        **agentcore_kwargs,
    ):
        self.omnichannel = AgentFrameworkBridge(
            tac=tac, create_agent=create_agent, channels=channels,
            config=config, auto_retrieve_memory=auto_retrieve_memory,
        )
        self.runtime = RuntimeServer(
            omnichannel=self.omnichannel, **agentcore_kwargs,
        )

    @property
    def app(self):
        return self.runtime.app

    def start(self, **kwargs):
        self.runtime.start(**kwargs)
```

---

## Usage Side-by-Side

### Interface 1 only — TACServer (deploy anywhere)

`AgentFrameworkBridge` is a pure request-processing object — it has no `start()` or `stop()` methods. Lifecycle is always owned by a server: `TACServer`, `RuntimeServer`, or a custom ASGI app. To run the handler standalone, wrap it in a `TACServer`:

```python
# MS Agent Framework                           # Strands
from tac_ms_agent_framework import (            from tac_strands import (
    AgentFrameworkBridge,                             AgentFrameworkBridge,
)                                               )
from tac.server import TACServer                from tac.server import TACServer

handler = AgentFrameworkBridge(                   handler = AgentFrameworkBridge(
    tac=tac,                                        tac=tac,
    create_agent=create_agent,                      create_agent=create_agent,
)                                               )
server = TACServer(                             server = TACServer(
    tac=tac,                                        tac=tac,
    voice_channel=handler.voice_channel,            voice_channel=handler.voice_channel,
    sms_channel=handler.sms_channel,                sms_channel=handler.sms_channel,
    config=handler.config,                          config=handler.config,
)                                               )
server.start()                                  server.start()
```

### Interface 1 + 2 — cloud runtime

```python
# MS Agent Framework + Foundry                 # Strands + AgentCore
from tac_ms_agent_framework import (            from tac_strands import (
    AgentFrameworkBridge,                             AgentFrameworkBridge,
    RuntimeServer,                                  RuntimeServer,
)                                               )

handler = AgentFrameworkBridge(                   handler = AgentFrameworkBridge(
    tac=tac,                                        tac=tac,
    create_agent=create_agent,                      create_agent=create_agent,
)                                               )
server = RuntimeServer(                         server = RuntimeServer(
    omnichannel=handler,                            omnichannel=handler,
    foundry_agent=my_foundry_agent,             )
)                                               server.start()
server.start()
```

### Interface 3 — combined

```python
# MS Agent Framework + Foundry                 # Strands + AgentCore
from tac_ms_agent_framework import (            from tac_strands import (
    OmniChannelServer,                              OmniChannelServer,
)                                               )

server = OmniChannelServer(                     server = OmniChannelServer(
    tac=tac,                                        tac=tac,
    create_agent=create_agent,                      create_agent=create_agent,
    foundry_agent=my_foundry_agent,             )
)                                               server.start()
server.start()
```

### Full control — use TACRoutes directly

```python
# Either SDK
handler = AgentFrameworkBridge(tac=tac, create_agent=factory)

# Create TACRoutes from the handler's channels (server-layer concern)
routes = TACRoutes(
    voice_channel=handler.voice_channel,
    sms_channel=handler.sms_channel,
    tac=tac,
    config=handler.config,
)

app = BedrockAgentCoreApp()
app.add_route("/twiml", routes.handle_twiml, methods=["POST"])
app.add_websocket_route("/ws", routes.handle_websocket)
app.add_route("/webhook", routes.handle_sms_webhook, methods=["POST"])
app.add_route("/conversation-relay-callback",
              routes.handle_conversation_relay_callback, methods=["POST"])

@app.entrypoint
async def invoke(payload):
    ...

app.run()
```

---

## What TAC Owns

TAC is the foundation. It provides everything Twilio-specific and framework-agnostic. Partner SDKs never duplicate this.

### Existing code (unchanged)

| Area | Files | What it provides |
|---|---|---|
| Core | `tac/core/tac.py` | `TAC` — `on_message_ready()`, `on_conversation_ended()`, `on_interrupt()`, `retrieve_memory()` |
| Config | `tac/core/config.py` | `TACConfig` — all Twilio credentials, `from_env()` |
| Voice | `tac/channels/voice.py` | `VoiceChannel` — `handle_incoming_call()`, `handle_websocket()`, `send_response()` (string or `AsyncGenerator`), `handle_conversation_relay_callback()` |
| SMS | `tac/channels/sms.py` | `SMSChannel` — `process_webhook()`, `send_response()` |
| Base | `tac/channels/base.py` | `BaseChannel` — conversation lifecycle, `_conversations` dict, `_retrieve_memory_if_enabled()` |
| WebSocket | `tac/channels/websocket_protocol.py` | `WebSocketProtocol`, `WebSocketDisconnectError` |
| Session | `tac/session/` | `SessionManager` ABC, `ThreadSafeSessionManager`, `SessionState` |
| Models | `tac/models/session.py` | `ConversationSession` — `conversation_id`, `profile_id`, `channel`, `profile`, `metadata` |
| Models | `tac/models/tac.py` | `TACMemoryResponse` — `observations`, `summaries`, `build_memory_prompts()` |
| Server config | `tac/server/config.py` | `TACServerConfig` — `host`, `port`, `public_domain`, path configs, `handoff_url`, `cintel_webhook_path` |
| Webhook validation | `tac/server/webhook.py` | `validate_twilio_webhook(request, auth_token, body)` — signature validation with proxy header support |
| Tools | `tac/tools/base.py` | `TACTool`, `function_tool`, `InjectedToolArg`, `.implementation`, `.configure_injection()` |
| Tools | `tac/tools/memory.py` | `create_memory_tool()` → `TACTool` with injected `MemoryClient` + `profile_id` |
| Tools | `tac/tools/knowledge.py` | `create_knowledge_tool()` → `TACTool` with injected `KnowledgeClient` |
| Tools | `tac/tools/handoff.py` | `create_handoff_tool()` |
| Clients | `tac/context/` | `MemoryClient`, `KnowledgeClient`, `ConversationClient` |

### New code in TAC

#### 1. `BaseChannel.get_conversation()` — public getter

Both SDKs currently access `self.voice_channel._conversations[conversation_id]` (private dict). TAC exposes a public method:

```python
# tac/channels/base.py — add to BaseChannel
def get_conversation(self, conversation_id: str) -> ConversationSession | None:
    """Get the ConversationSession for an active conversation."""
    return self._conversations.get(conversation_id)
```

3 lines. Eliminates private access in both SDKs.

#### 2. `TACRoutes` — framework-agnostic route handlers

Extracted from `TACServer._create_app()` into a reusable class. Uses Starlette types (`Request`, `Response`, `WebSocket`) so any ASGI framework can mount them.

```python
# tac/server/routes.py (new file)

class TACRoutes:
    """Framework-agnostic route handlers using Starlette types.

    Compatible with FastAPI, BedrockAgentCoreApp, FoundryCBAgent,
    and any ASGI framework built on Starlette.
    """

    def __init__(
        self,
        voice_channel=None,
        sms_channel=None,
        tac=None,
        config=None,
        validate_webhooks: bool = True,
    ):
        self.voice_channel = voice_channel
        self.sms_channel = sms_channel
        self.tac = tac
        self.config = config or TACServerConfig.from_env()
        self.validate_webhooks = validate_webhooks

    async def handle_twiml(self, request: Request) -> Response: ...
    async def handle_websocket(self, websocket: WebSocket) -> None: ...
    async def handle_sms_webhook(self, request: Request) -> JSONResponse: ...
    async def handle_conversation_relay_callback(self, request: Request) -> Response: ...
    async def handle_cintel_webhook(self, request: Request) -> JSONResponse: ...
```

~90 lines. The route logic is moved from `TACServer._create_app()` — no new logic, just restructured.

**Webhook signature validation.** TAC already provides `validate_twilio_webhook(request, auth_token, body)` in `tac/server/webhook.py`. It validates the `X-Twilio-Signature` header, handles proxy headers (`X-Forwarded-Proto`, `X-Forwarded-Host`) for ngrok-style environments, and works with both JSON (SMS from Maestro) and form-encoded (voice) bodies.

`TACRoutes` applies validation in `handle_twiml` and `handle_sms_webhook` when `validate_webhooks=True` (the default). WebSocket connections are not validated — Twilio does not sign WebSocket upgrade requests. `handle_conversation_relay_callback` is validated because it carries form-encoded data signed by Twilio.

```python
# Inside TACRoutes route handlers:
async def handle_twiml(self, request: Request) -> Response:
    if self.validate_webhooks:
        form_data = await request.form()
        if not validate_twilio_webhook(request, self.tac.config.twilio_auth_token, form_data):
            return Response(content="Invalid signature", status_code=403)
    ...

async def handle_sms_webhook(self, request: Request) -> JSONResponse:
    if self.validate_webhooks:
        body = await request.body()
        if not validate_twilio_webhook(request, self.tac.config.twilio_auth_token, body.decode()):
            return JSONResponse(content={"error": "Invalid signature"}, status_code=403)
    ...
```

The `validate_webhooks` parameter flows through `AgentFrameworkBridge` and `OmniChannelServer` constructors:

```python
class AgentFrameworkBridge:
    def __init__(
        self,
        tac: TAC,
        create_agent: ...,
        *,
        validate_webhooks: bool = True,   # passed to TACRoutes
        ...
    ): ...
```

Developers disable validation during local development (signature checks fail without ngrok or a tunnel) and enable it in production. The current Azure SDK's `validate_webhooks` parameter maps directly to this.

#### 3. Refactored `TACServer`

Uses `TACRoutes` internally. Adds `serve_async()` and `stop()`. Lazy `app` property. Constructor signature unchanged — no breaking changes.

```python
# tac/server/server.py (modified)

class TACServer:
    def __init__(
        self,
        tac: TAC,
        voice_channel: VoiceChannel | None = None,
        sms_channel: SMSChannel | None = None,
        config: TACServerConfig | None = None,
    ) -> None:
        self.tac = tac
        self.config = config or TACServerConfig.from_env()
        self.voice_channel = voice_channel
        self.sms_channel = sms_channel
        self.routes = TACRoutes(
            voice_channel=voice_channel, sms_channel=sms_channel,
            tac=tac, config=self.config,
        )
        self._app: FastAPI | None = None
        self._server = None

    @property
    def app(self) -> FastAPI:
        if self._app is None:
            self._app = self._create_app()
        return self._app

    def _create_app(self) -> FastAPI:
        app = FastAPI(title="TAC Server")
        r, c = self.routes, self.config
        if r.sms_channel is not None:
            app.post(c.sms_webhook_path)(r.handle_sms_webhook)
        if r.voice_channel is not None:
            if c.handoff_url:
                r.voice_channel.enable_close_on_disconnect()
            app.post(c.twiml_path)(r.handle_twiml)
            app.websocket(c.websocket_path)(r.handle_websocket)
            app.post(c.conversation_relay_callback_path)(
                r.handle_conversation_relay_callback)
        if c.cintel_webhook_path is not None:
            app.post(c.cintel_webhook_path)(r.handle_cintel_webhook)
        app.get("/health")(lambda: {"status": "ok"})
        return app

    def start(self) -> None: ...
    async def serve_async(self) -> None: ...
    def stop(self) -> None: ...
```

#### 4. `MessageHandler` protocol (static type checking only)

```python
# tac/protocols.py (new file)

from __future__ import annotations
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    class MessageHandler(Protocol):
        """Interface that partner SDK handlers implement.

        Not enforced at runtime — partner SDKs wire callbacks to TAC
        directly via tac.on_message_ready(). This protocol exists
        solely to formalize the callback shape for type checkers
        and documentation.
        """
        async def handle_message(
            self, user_message: str, context: ConversationSession,
            memory: TACMemoryResponse | None,
        ) -> None: ...

        async def handle_conversation_ended(
            self, context: ConversationSession,
        ) -> None: ...

        async def handle_interrupt(
            self, context: ConversationSession,
            interrupt_data: Any,
        ) -> None: ...
```

~20 lines. Guarded behind `TYPE_CHECKING` — never importable at runtime, never used with `isinstance()`. Exists purely so type checkers (mypy, pyright) and IDE tooling can validate that partner SDK handlers conform to the expected callback signatures. The `handle_interrupt` method formalizes the voice interrupt callback that both SDKs must implement for proper streaming cancellation.

#### Summary of TAC changes

| Change | File | Size |
|---|---|---|
| `get_conversation()` | `channels/base.py` | 3 lines added |
| `TACRoutes` | `server/routes.py` | ~90 lines (new file, logic moved from server.py, + webhook validation integration) |
| Refactored `TACServer` | `server/server.py` | Net ~0 (restructure + `serve_async`/`stop`) |
| `MessageHandler` protocol | `protocols.py` | ~20 lines (new file, `TYPE_CHECKING` only) |
| Updated exports | `server/__init__.py` | 2 lines |

---

## What Partner SDKs Own

Each partner SDK bridges a specific agent framework with TAC. It owns all agent-specific code: agent creation, streaming, SMS execution, session persistence, cleanup. It also owns the cloud runtime server wrapper.

### File structure (both SDKs, symmetric)

```
tac_ms_agent_framework/                    tac_strands/
├── __init__.py                        ├── __init__.py
├── handler.py                         ├── handler.py
│   └── AgentFrameworkBridge             │   └── AgentFrameworkBridge
├── runtime_server.py                  ├── runtime_server.py
│   └── RuntimeServer                  │   └── RuntimeServer
├── server.py                          ├── server.py
│   └── OmniChannelServer              │   └── OmniChannelServer
├── types.py                           ├── agent_proxy.py
│   ├── AgentSessionStore              │   ├── AgentProxy (ABC)
│   └── InMemoryAgentSessionStore      │   ├── LocalAgentProxy
├── utils.py                           │   └── RemoteAgentProxy
│   └── format_memory_context          ├── tools/
├── tools/                             │   ├── _convert.py
│   ├── _convert.py                    │   │   └── _as_tool (internal)
│   │   └── _as_tool (internal)        │   ├── memory.py
│   ├── memory.py                      │   │   └── create_memory_recall_tool
│   │   └── create_memory_recall_tool  │   └── knowledge.py
│   └── knowledge.py                   │       └── create_knowledge_tool
│       ├── create_knowledge_tool      └── (no utils.py)
│       └── fetch_knowledge_base_info
└── (no agent_proxy.py)
```

### What each file contains and why it's in the SDK

#### `handler.py` — `AgentFrameworkBridge` (Interface 1)

The bulk of each SDK. Contains all framework-specific agent logic.

| Responsibility | Why it's in the SDK |
|---|---|
| Channel creation + callback wiring | Convenience — TAC provides pieces, SDK assembles them. Wires all three callbacks: `on_message_ready`, `on_conversation_ended`, `on_interrupt`. |
| `_stream_response()` | Agent Framework: `agent.run(stream=True)` yields `.text` chunks. Strands: `agent.stream_async()` yields `contentBlockDelta` events. Different protocols. |
| `_get_or_create_voice_agent()` | Agent Framework: caches `Agent` + `AgentSession`. Strands: caches `AgentProxy`. Different types. |
| `_cleanup_voice_agent()` | Agent Framework: pop agent + `AgentSession` from caches, final background-save to `AgentSessionStore`. Strands: pop `AgentProxy`, call `agent.cleanup()` (triggers `SessionManager` persistence). Different lifecycle. |
| `_handle_conversation_ended()` | Called by TAC when conversation closes (voice: WebSocket disconnect → `BaseChannel._end_conversation()`; SMS: conversation updated to CLOSED). Agent Framework: final save of `AgentSession` to store, pop from caches. Strands: call `agent.cleanup()`, pop from caches. For voice, this is the authoritative cleanup path (distinct from `_cleanup_voice_agent` which handles mid-stream errors). For SMS, optionally deletes the session store entry. |
| `_handle_interrupt()` | Called by TAC when user interrupts mid-speech (voice only). Agent Framework: no-op (TAC's `SessionState.cancel_stream_task()` handles cancellation; the `AgentSession` retains partial history). Strands: no-op for the same reason. The SDK registers this callback to have a hook for future framework-specific interrupt cleanup (e.g., aborting tool execution), but the default implementation can be empty since TAC handles task cancellation internally. |
| `_handle_sms()` | Agent Framework: load session, augment with memory, `agent.run()`, save session. Strands: ephemeral agent, `agent.run_async()`, parse Bedrock response format, cleanup. |
| Channel dispatch | Routes `voice` vs `sms` to framework-specific methods |

**Conversation state ownership (intentional asymmetry).** `ConversationSession` (TAC) is metadata — profile, channel, phone numbers — not conversation message history. Conversation message history is managed entirely by each SDK via framework-specific mechanisms. The handler interface does not prescribe a state model; each SDK chooses what fits its framework. See the "Conversation State Management" section below for the full picture.

#### `runtime_server.py` — `RuntimeServer` (Interface 2)

Creates `TACRoutes` from the handler's channels and mounts them on the cloud runtime app:

| SDK | What it creates | What it mounts |
|---|---|---|
| MS Agent Framework | `FoundryCBAgent` Starlette app | TAC routes via `app.routes.extend(...)` |
| Strands | `BedrockAgentCoreApp` | TAC routes via `app.add_route(...)` |

#### `server.py` — `OmniChannelServer` (Interface 3)

Pure composition — creates `AgentFrameworkBridge` + `RuntimeServer`. No logic of its own.

#### `types.py` (MS Agent Framework only)

`AgentSessionStore` protocol + `InMemoryAgentSessionStore`. This is MS Agent Framework-specific because Agent Framework **externalizes** session management — the handler must explicitly `load()` and `save()` `AgentSession` objects around each agent call. Strands doesn't need this protocol because Strands **internalizes** session management: the `Agent` manages its own state via `SessionManager` (configured at agent creation, reads/writes handled by the framework automatically).

#### `agent_proxy.py` (Strands only)

`AgentProxy` ABC, `LocalAgentProxy`, `RemoteAgentProxy`. Abstracts local Strands `Agent` vs remote Bedrock AgentCore runtime. MS Agent Framework doesn't need this because the Agent Framework SDK natively supports multiple providers (Responses API, Chat Completions, Foundry Agent Service) — the developer picks a provider via `client.as_agent()`, and the framework handles local vs remote internally.

**Why AgentProxy exists and why it's kept:**

Strands doesn't have a native remote-agent abstraction equivalent to Agent Framework's provider model. `AgentProxy` fills this gap at the SDK layer:

- **`LocalAgentProxy`** wraps a local Strands `Agent`. It does non-trivial work: `run_async()` collects the full stream from `agent.stream_async()` and normalizes the response into a consistent dict format (extracting `text` from Bedrock `contentBlockDelta` events). `stream_async()` delegates directly for voice streaming. `cleanup()` calls `agent.cleanup()` to trigger `SessionManager` persistence.

- **`RemoteAgentProxy`** wraps `invoke_agent_runtime()` from the `bedrock-agentcore` SDK. It sends prompts to a remote agent running in its own AgentCore container and receives responses. The remote agent manages its own conversation state via its own `SessionManager`. The `runtime_session_id` parameter (set to TAC's `conversation_id`) correlates requests to the same remote session.

**The two deployment topologies for Strands + AgentCore:**

| | Topology A: In-process | Topology B: Remote invocation |
|---|---|---|
| **Where agent runs** | In the same container (local or AgentCore-hosted) | In a separate AgentCore container |
| **Proxy type** | `LocalAgentProxy` | `RemoteAgentProxy` |
| **State management** | Agent manages via its own `SessionManager` (File, S3, Repository) | Remote agent manages its own state; proxy is stateless |
| **Use case** | Simple deployments, full control over agent, direct tool access | Multi-agent architectures, shared agent services, team separation |
| **Azure parallel** | `client.as_agent()` with Responses API or Chat Completions provider | `client.as_agent()` with Foundry Agent Service provider |

Both topologies use the same `AgentFrameworkBridge` — the handler calls `agent.stream_async()` or `agent.run_async()` on the `AgentProxy` without knowing which topology is in use. The `create_agent` factory returns the appropriate proxy type based on deployment configuration.

#### `utils.py` (MS Agent Framework only)

`format_memory_context()` — composes `TACMemoryResponse` into augmented prompt string for SMS. Strands agents use the memory recall tool directly instead.

#### `tools/` — tool bridges

Covered in the next section.

### Exports

**`tac_ms_agent_framework`:**
```python
# Core interfaces (same names as Strands)
AgentFrameworkBridge, RuntimeServer, OmniChannelServer

# MS Agent Framework-specific
AgentSessionStore, InMemoryAgentSessionStore, format_memory_context

# Tool factories
tools.create_memory_recall_tool
tools.create_knowledge_tool
tools.fetch_knowledge_base_info, tools.KnowledgeBaseInfo
```

**`tac_strands`:**
```python
# Core interfaces (same names as MS Agent Framework)
AgentFrameworkBridge, RuntimeServer, OmniChannelServer

# Strands-specific
AgentProxy, LocalAgentProxy, RemoteAgentProxy

# Tool factories
tools.create_memory_recall_tool
tools.create_knowledge_tool
```

---

## Conversation State Management

### Two distinct objects

TAC's `ConversationSession` and the agent framework's conversation state are separate concerns:

| | `ConversationSession` (TAC) | Agent conversation state (SDK) |
|---|---|---|
| **What it holds** | Metadata: `conversation_id`, `profile_id`, `channel`, phone numbers, `profile` traits, `author_info` | Message history: user/assistant turns, tool calls, Foundry thread IDs, session config |
| **Created by** | TAC's `BaseChannel._start_conversation()` | SDK's handler — framework-specific |
| **Lifetime** | Duration of the TAC conversation (from first webhook/setup to close) | Depends on channel and SDK (see below) |
| **Persisted by** | TAC (in-memory dict, not externally persisted) | SDK — `AgentSessionStore` (MS AF) or `FileSessionManager` (Strands) |
| **Passed to `create_agent`** | Yes — the whole object | No — the factory *creates* framework state internally |

### How each SDK manages conversation history

#### MS Agent Framework

**Voice (standalone or Foundry):**

```
Utterance 1 → _get_or_create_voice_agent(conv_id)
                ├─ create_agent(ConversationSession) → Agent (cached)
                └─ _get_or_create_voice_session(conv_id) → AgentSession (cached)
              agent.run(prompt, stream=True, session=af_session)
              _background_save_session(conv_id, af_session)  # fire-and-forget

Utterance 2 → same Agent, same AgentSession (history accumulates in-memory)
              agent.run(prompt, stream=True, session=af_session)
              _background_save_session(conv_id, af_session)

Disconnect  → _cleanup_voice_agent(conv_id)
              pop Agent + AgentSession from caches
              final background save
```

- `Agent` is created once per call, cached in `_voice_agents[conv_id]`.
- `AgentSession` is created once per call, cached in `_voice_sessions[conv_id]`.
- History accumulates across utterances because the same `AgentSession` is reused.
- Background save to `AgentSessionStore` after each utterance for durability.

**SMS (standalone or Foundry):**

```
Message 1 → create_agent(ConversationSession) → Agent (ephemeral)
            session_store.load(conv_id) → AgentSession or None
            if None: AgentSession(session_id=conv_id)
            agent.run(augmented_message, session=af_session)
            session_store.save(conv_id, af_session)  # blocking, in finally

Message 2 → create_agent(ConversationSession) → new Agent
            session_store.load(conv_id) → restored AgentSession (with history)
            agent.run(augmented_message, session=af_session)
            session_store.save(conv_id, af_session)
```

- Agent is ephemeral (new per message), but `AgentSession` persists via `AgentSessionStore`.
- `AgentSession.to_dict()`/`from_dict()` serializes full message history, thread IDs, etc.
- `InMemoryAgentSessionStore` for single-instance; developers provide Redis/CosmosDB for scaling.

#### Foundry Agent Service: conversation_id → thread correlation

When using Foundry Agent Service, conversation history lives **server-side on Foundry**, not in the `AgentSession` object. The `AgentSession` acts as a thin client-side reference:

**Key field:** `AgentSession.service_session_id` — this is the Foundry thread ID.

**How the correlation works:**

```
                    TAC                         AgentSessionStore              Foundry
                     │                                │                          │
  Twilio call ──────▶│ conversation_id = "conv_123"   │                          │
                     │                                │                          │
  1st utterance ────▶│ session_store.load("conv_123") │                          │
                     │────────────────────────────────▶│ returns None             │
                     │                                │                          │
                     │ AgentSession(session_id="conv_123")                       │
                     │   .service_session_id = None    │                          │
                     │                                │                          │
                     │ agent.run(prompt, session=af_session)                     │
                     │────────────────────────────────────────────────────────────▶│
                     │                                │     creates thread       │
                     │                                │     thread_id = "th_abc" │
                     │◀────────────────────────────────────────────────────────────│
                     │ af_session.service_session_id = "th_abc"  (mutated)       │
                     │                                │                          │
                     │ session_store.save("conv_123", af_session)                │
                     │────────────────────────────────▶│ saves {                  │
                     │                                │   session_id: "conv_123" │
                     │                                │   service_session_id:     │
                     │                                │     "th_abc"             │
                     │                                │   state: {...}           │
                     │                                │ }                        │
                     │                                │                          │
  2nd utterance ────▶│ session_store.load("conv_123") │                          │
                     │────────────────────────────────▶│ returns AgentSession     │
                     │ af_session.service_session_id = "th_abc"                  │
                     │                                │                          │
                     │ agent.run(prompt, session=af_session)                     │
                     │────────────────────────────────────────────────────────────▶│
                     │                                │  reuses thread "th_abc"  │
                     │◀────────────────────────────────────────────────────────────│
```

**The correlation chain:**
1. Twilio provides `conversation_id` (e.g., `"conv_123"`) — this is the TAC key.
2. `AgentSessionStore` uses `conversation_id` as its storage key.
3. On first `agent.run()`, Foundry creates a server-side thread and Agent Framework writes the thread ID into `af_session.service_session_id`.
4. `session_store.save("conv_123", af_session)` persists the mapping: `conversation_id → service_session_id (Foundry thread)`.
5. On subsequent messages, `session_store.load("conv_123")` restores the `AgentSession` with its `service_session_id`, and Agent Framework reuses the Foundry thread.

**What `AgentSession` holds varies by provider:**

| Provider | `service_session_id` | `state` dict |
|---|---|---|
| **Foundry Agent Service** | Foundry thread ID (`"th_abc"`) — history lives server-side | Minimal (thread reference, config) |
| **Responses API** | None | Full message history via `InMemoryHistoryProvider` |
| **Chat Completions** | None | Full message history |

All three serialize identically via `to_dict()`/`from_dict()`. The store doesn't know or care which provider is in use.

**Edge cases:**

- **Store loses the session** (e.g., `InMemoryAgentSessionStore` after restart): Next message creates a fresh `AgentSession` with no `service_session_id`. Agent Framework creates a **new** Foundry thread. The old thread is orphaned server-side. Conversation history restarts. This is why the `finally` block always saves — even on error, the session may contain a newly created `service_session_id`.
- **Voice WebSocket reconnects** (rare, e.g., network hiccup): TAC creates a new conversation. The voice handler creates a fresh `AgentSession`. If the previous session was background-saved, a custom recovery flow *could* reload it by `conversation_id` — but the current implementation doesn't do this. Each WebSocket connection starts fresh.
- **Multiple instances (horizontal scaling)**: With `InMemoryAgentSessionStore`, two instances handling the same conversation will create separate Foundry threads. Use a shared store (Redis, CosmosDB) to avoid this.

#### `AgentSessionStore` interface: does it need changes for Foundry?

**No.** The interface works unchanged for all deployment modes:

```python
class AgentSessionStore(Protocol):
    async def load(self, session_id: str) -> AgentSession | None: ...
    async def save(self, session_id: str, session: AgentSession) -> None: ...
```

This works because:

1. **The store is provider-agnostic.** It stores opaque `AgentSession` objects. Whether the session contains a Foundry `service_session_id`, Responses API message history, or both — the store doesn't care. `to_dict()`/`from_dict()` handles all serialization.

2. **The key is always `conversation_id`.** Both voice and SMS use TAC's `conversation_id` as the store key. Foundry's thread ID is *inside* the session, not the key. The store never needs to know about Foundry threads.

3. **No Foundry-specific lifecycle hooks needed.** Thread creation is handled by Agent Framework on `agent.run()`. Thread cleanup (if needed) would be handled by Foundry's TTL policies, not by the store.

The only scenario where the interface might need extension is **session deletion** — the current protocol has only `load`/`save`. The `FileAgentSessionStore` example adds a `delete()` method (used in `on_conversation_ended` to clean up files), but it's not part of the protocol. If cleanup becomes a common pattern, adding an optional `delete(session_id)` method to the protocol would be worth considering. This is a minor addition and doesn't affect Foundry compatibility.

#### Strands

**Voice (standalone — Topology A: in-process agent):**

```
Utterance 1 → _get_or_create_voice_agent(conv_id)
                ├─ create_agent(ConversationSession) → AgentProxy (cached)
                │   └─ internally creates:
                │       ├─ SessionManager(session_id=conversation_id)
                │       ├─ SummarizingConversationManager(...)
                │       └─ Agent(session_manager=..., conversation_manager=...)
                │       └─ LocalAgentProxy(agent)
                └─ agent.stream_async(prompt) → yields chunks

Utterance 2 → same AgentProxy (cached)
              agent.stream_async(prompt) → history managed by Agent internally

Disconnect  → _cleanup_voice_agent(conv_id)
              agent.cleanup() → SessionManager persists state
              del agent
```

- `LocalAgentProxy` wraps a Strands `Agent` that holds its own history via `SummarizingConversationManager`.
- `SessionManager` persists to storage keyed by `conversation_id` (per-call, not per-customer). Developers choose the `SessionManager` implementation:
  - `FileSessionManager` — local development (writes to `/tmp/sessions/{conversation_id}`)
  - `S3SessionManager` — production / AgentCore (durable, works across instances)
  - `RepositorySessionManager` — custom backend (Redis, DynamoDB, etc.)
- Conversation history lives inside the `Agent` object in-memory during the call; `SessionManager` reads on agent creation and writes on `cleanup()`.
- This same topology works when deployed on Bedrock AgentCore — the agent runs in-process inside the container. AgentCore is a **hosting shell** (provides `/ping` health, `/invocations` entry point, task tracking) but does **not** manage conversation state server-side. The agent must manage its own state via `SessionManager`.

**Voice (Topology B: remote agent via AgentCore):**

```
Utterance 1 → _get_or_create_voice_agent(conv_id)
                ├─ create_agent(ConversationSession) → RemoteAgentProxy (cached)
                │   └─ configured with:
                │       ├─ agent_id (AgentCore runtime ID)
                │       └─ runtime_session_id=conversation_id
                └─ agent.stream_async(prompt)
                    └─ invoke_agent_runtime(prompt, runtimeSessionId=conversation_id)
                    └─ remote agent manages its own state

Utterance 2 → same RemoteAgentProxy (cached)
              agent.stream_async(prompt) → remote agent accumulates history

Disconnect  → _cleanup_voice_agent(conv_id)
              agent.cleanup() (no-op — state lives on remote)
```

- `RemoteAgentProxy` calls AgentCore's `invoke_agent_runtime` API. The remote agent (running in its own AgentCore container) manages state internally via its own `SessionManager`.
- `runtime_session_id` (set to TAC's `conversation_id`) correlates requests to the same remote session.
- This is the Strands equivalent of Azure's Foundry Agent Service pattern — the agent runs remotely, and the SDK holds a thin proxy.

**SMS (standalone or AgentCore — Topology A):**

```
Message 1 → create_agent(ConversationSession) → AgentProxy (ephemeral)
              └─ LocalAgentProxy wrapping Agent with:
                  ├─ SessionManager(session_id=conversation_id)
                  └─ loads history from storage
            agent.run_async(user_message)
            agent.cleanup() → saves history via SessionManager
            del agent

Message 2 → create_agent(ConversationSession) → new AgentProxy
              └─ Agent reloads history from same SessionManager location
            agent.run_async(user_message)
            agent.cleanup()
```

- Agent is ephemeral per message, but `SessionManager` persists history keyed by `conversation_id`.
- The new architecture passes `ConversationSession` from TAC, fixing two bugs in the current examples: `channel` was hardcoded to `"voice"`, and sessions were keyed by `profile_id` instead of `conversation_id`.
- For Topology B (remote), replace `LocalAgentProxy` with `RemoteAgentProxy` — the factory returns the appropriate proxy type based on deployment configuration.

### Key differences summarized

| Aspect | MS Agent Framework | Strands |
|---|---|---|
| Voice history storage | `AgentSession` in-memory, background-saved to `AgentSessionStore` | Strands `Agent` in-memory, `SessionManager` persists on `cleanup()` |
| Voice history key | `conversation_id` | `conversation_id` |
| SMS history storage | `AgentSession` via `AgentSessionStore` (load/save per message) | `SessionManager` (load on creation, save on `cleanup()` per message) |
| SMS history key | `conversation_id` | `conversation_id` |
| External persistence protocol | `AgentSessionStore` — SDK-defined protocol (pluggable: Redis, CosmosDB, etc.) | `SessionManager` — Strands-native (pluggable: `FileSessionManager`, `S3SessionManager`, `RepositorySessionManager`) |
| State management ownership | SDK manages load/save around agent calls (`handler` orchestrates) | Framework-internal — `Agent` manages its own state via `SessionManager` |
| Cloud runtime state (Topology A) | Foundry: server-side thread, `AgentSession` holds `service_session_id` | AgentCore: agent runs in-process, manages own state via `SessionManager` (AgentCore is a hosting shell) |
| Cloud runtime state (Topology B) | N/A (Foundry is always Topology A from SDK perspective) | AgentCore: `RemoteAgentProxy` invokes remote agent via `invoke_agent_runtime`, remote manages its own state |
| History across calls | New `AgentSession` per call (fresh history), but memory recall provides cross-call context | New agent per call with new `SessionManager` keyed by `conversation_id` (fresh history per call), memory recall provides cross-call context |

### What `ConversationSession` provides to the factory

The `create_agent` factory receives `ConversationSession` to configure the agent, not to provide message history:

```python
# MS Agent Framework example
def create_agent(session: ConversationSession) -> Agent:
    prompt = VOICE_PROMPT if session.channel == "voice" else SMS_PROMPT  # channel routing
    tools = [
        create_memory_recall_tool(tac, session),  # needs profile_id, conversation_id
        create_knowledge_tool(tac, kb_id),
    ]
    return client.as_agent(name="Agent", instructions=prompt, tools=tools)

# Strands example — Topology A (in-process agent)
def create_agent(session: ConversationSession) -> AgentProxy:
    session_mgr = FileSessionManager(session_id=session.conversation_id)  # local dev
    # For production: S3SessionManager(session_id=session.conversation_id)
    recall_tool = create_memory_recall_tool(tac, session)
    prompt = VOICE_PROMPT if session.channel == "voice" else SMS_PROMPT
    agent = Agent(model=model, tools=[recall_tool, ...],
                  session_manager=session_mgr, system_prompt=prompt)
    return LocalAgentProxy(agent)

# Strands example — Topology B (remote agent via AgentCore)
def create_agent(session: ConversationSession) -> AgentProxy:
    return RemoteAgentProxy(
        agent_id=AGENTCORE_RUNTIME_ID,
        runtime_session_id=session.conversation_id,
    )
```

The factory uses `ConversationSession` for:
- **`session.channel`** — choose voice vs SMS system prompt, tool configuration
- **`session.profile_id`** — key for session persistence, memory tool injection
- **`session.conversation_id`** — key for agent caching, memory tool injection
- **`session.profile`** — customer traits for prompt personalization (if populated)

Message history is never in `ConversationSession`. It's managed by `AgentSession` (MS AF) or `Agent` + `SessionManager` (Strands).

---

## Tool Calling

### Principle

TAC owns all tool logic. Each SDK provides convenience factories that return framework-native tools. Developers never see `TACTool` or deal with format conversion.

### How it works

```
Developer calls SDK factory
        │
        ▼
SDK factory calls TAC's tool factory
        │
        ▼
TAC creates TACTool (logic, schema, injection)
        │
        ▼
SDK converts TACTool to framework-native format (internal)
        │
        ▼
Developer gets back a framework-native tool
```

### TAC's tool system (unchanged)

TAC provides `TACTool` — a framework-agnostic tool representation:

```python
# tac/tools/base.py
class TACTool:
    name: str
    description: str
    params_json_schema: dict

    @property
    def implementation(self) -> Callable:
        """Clean async callable with proper __name__, __doc__, __signature__."""

    def configure_injection(self, **kwargs) -> TACTool:
        """Bind runtime dependencies (MemoryClient, KnowledgeClient, etc.)."""
```

TAC provides factories that create configured `TACTool` instances:

```python
# tac/tools/memory.py
create_memory_tool(memory_client, session) -> TACTool

# tac/tools/knowledge.py
create_knowledge_tool(knowledge_client, kb_id, tool_config) -> TACTool

# tac/tools/handoff.py
create_handoff_tool(...) -> TACTool
```

### SDK's internal converter (not public)

Each SDK has one internal function that converts any `TACTool` to its framework's format:

**ms-agent-framework-twilio-agent-connect-python:**

```python
# tac_ms_agent_framework/tools/_convert.py

from tac.tools.base import TACTool


def _as_tool(tac_tool: TACTool):
    """Internal: convert TACTool to Agent Framework callable.

    Agent Framework discovers tools by introspecting function name,
    docstring, and type annotations. TACTool.implementation provides
    all three.
    """
    return tac_tool.implementation
```

**strands-twilio-agent-connect-python:**

```python
# tac_strands/tools/_convert.py

from strands import tool as strands_tool
from tac.tools.base import TACTool


def _as_tool(tac_tool: TACTool):
    """Internal: convert TACTool to Strands @tool-decorated function.

    Wraps TACTool.implementation with Strands' @tool decorator,
    preserving name, description, and parameter schema.
    """
    return strands_tool(
        name=tac_tool.name,
        description=tac_tool.description,
    )(tac_tool.implementation)
```

### SDK's convenience factories (public API)

Thin wrappers: call TAC's factory + internal converter. This is all the developer sees.

**ms-agent-framework-twilio-agent-connect-python:**

```python
# tac_ms_agent_framework/tools/memory.py

from tac.tools.memory import create_memory_tool as _tac_create
from tac_ms_agent_framework.tools._convert import _as_tool


def create_memory_recall_tool(tac, session):
    """Create a memory recall tool for Agent Framework agents."""
    if tac.memora_client is None:
        raise ValueError("TAC memora_client is not initialised.")
    return _as_tool(_tac_create(tac.memora_client, session))
```

```python
# tac_ms_agent_framework/tools/knowledge.py

from tac.tools.knowledge import create_knowledge_tool as _tac_create
from tac_ms_agent_framework.tools._convert import _as_tool


async def create_knowledge_tool(tac, knowledge_base_id, tool_config=None):
    """Create a knowledge search tool for Agent Framework agents."""
    if not knowledge_base_id or tac.knowledge_client is None:
        return None
    tac_tool = await _tac_create(tac.knowledge_client, knowledge_base_id, tool_config)
    return _as_tool(tac_tool)
```

**strands-twilio-agent-connect-python — identical shape:**

```python
# tac_strands/tools/memory.py

from tac.tools.memory import create_memory_tool as _tac_create
from tac_strands.tools._convert import _as_tool


def create_memory_recall_tool(tac, session):
    """Create a memory recall tool for Strands agents."""
    if tac.memora_client is None:
        raise ValueError("TAC memora_client is not initialised.")
    return _as_tool(_tac_create(tac.memora_client, session))
```

```python
# tac_strands/tools/knowledge.py

from tac.tools.knowledge import create_knowledge_tool as _tac_create
from tac_strands.tools._convert import _as_tool


async def create_knowledge_tool(tac, knowledge_base_id, tool_config=None):
    """Create a knowledge search tool for Strands agents."""
    if not knowledge_base_id or tac.knowledge_client is None:
        return None
    tac_tool = await _tac_create(tac.knowledge_client, knowledge_base_id, tool_config)
    return _as_tool(tac_tool)
```

### What developers write

```python
# MS Agent Framework
from tac_ms_agent_framework.tools import create_memory_recall_tool, create_knowledge_tool

tools = [
    create_memory_recall_tool(tac, session),          # returns Agent Framework callable
    await create_knowledge_tool(tac, kb_id),           # returns Agent Framework callable
    look_up_outage,                                    # developer's own @ai_function
]
agent = client.as_agent(tools=tools)
```

```python
# Strands
from tac_strands.tools import create_memory_recall_tool, create_knowledge_tool

tools = [
    create_memory_recall_tool(tac, session),          # returns @tool-decorated function
    await create_knowledge_tool(tac, kb_id),           # returns @tool-decorated function
    look_up_outage,                                    # developer's own @tool
]
agent = Agent(tools=tools)
```

Developers never import `_as_tool`, never see `TACTool`, never think about conversion. They call a factory, get back a tool in their framework's format, pass it to their agent. TAC tools and custom tools go in the same list.

### Tool ownership summary

| | TAC | Partner SDK |
|---|---|---|
| Tool logic | `create_memory_tool()`, `create_knowledge_tool()`, `create_handoff_tool()` | Nothing — delegates to TAC |
| Tool format | `TACTool` with `.implementation`, `.name`, `.description`, `.params_json_schema` | `_as_tool()` — internal converter (not public) |
| Public API | `TACTool` factories that take internal clients (`MemoryClient`, etc.) | `create_memory_recall_tool(tac, session)` — takes `tac`, calls TAC + converts |
| Custom tools | `@function_tool` decorator, `TACTool` base class | Not involved — developers use framework-native decorators (`@ai_function`, `@tool`) |

### Where each tool type comes from

| Tool | Developer creates with | Conversion needed? |
|---|---|---|
| Memory recall | `create_memory_recall_tool(tac, session)` from SDK | No — factory handles it |
| Knowledge search | `create_knowledge_tool(tac, kb_id)` from SDK | No — factory handles it |
| Handoff | `create_handoff_tool(...)` from SDK | No — factory handles it |
| Custom business logic | `@ai_function` / `@tool` (framework-native) | No — already native |

---

## Full Ownership Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                         DEVELOPER CODE                              │
│  create_agent factory, system prompts, @ai_function / @tool,        │
│  TACConfig, env vars                                                │
└─────────────────────────────┬───────────────────────────────────────┘
                              │
         ┌────────────────────┼─────────────────────┐
         │                    │                      │
         ▼                    ▼                      ▼
┌─────────────────┐  ┌────────────────┐  ┌───────────────────┐
│ OmniChannelHdlr │  │ RuntimeServer  │  │ OmniChannelServer │
│ (Interface 1)   │  │ (Interface 2)  │  │ (Interface 3)     │
│                 │  │                │  │ = 1 + 2 composed  │
│ PARTNER SDK     │  │ PARTNER SDK    │  │ PARTNER SDK       │
├─────────────────┤  ├────────────────┤  └───────────────────┘
│ Streaming bridge│  │ Mount TACRoutes│
│ SMS execution   │  │ on cloud app   │
│ Agent caching   │  │ (Foundry /     │
│ Session persist │  │  AgentCore)    │
│ Channel dispatch│  │                │
│ Error handling  │  │                │
│ Cleanup         │  │                │
│ _as_tool() conv │  │                │
│ Tool factories  │  │                │
└────────┬────────┘  └───────┬────────┘
         │                   │
         │    ┌──────────────┘
         │    │
         ▼    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                           TAC                                       │
│                                                                     │
│  Channels          Server           Tools          Core             │
│  ┌──────────┐     ┌───────────┐   ┌───────────┐  ┌─────────────┐  │
│  │VoiceChan │     │TACRoutes  │   │TACTool    │  │TAC          │  │
│  │ send_resp│     │ handle_*  │   │ .impl     │  │ on_msg_ready│  │
│  │ handle_ws│     │           │   │ .config_  │  │ on_conv_end │  │
│  │ handle_  │     │TACServer  │   │  inject   │  │ on_interrupt│  │
│  │ incoming │     │ (FastAPI) │   │           │  │ retrieve_   │  │
│  │ get_conv │     │           │   │create_    │  │  memory     │  │
│  │          │     │TACServer  │   │ memory_   │  │             │  │
│  │SMSChannel│     │  Config   │   │ tool      │  │TACConfig    │  │
│  │ process_ │     │           │   │create_    │  │ from_env()  │  │
│  │ webhook  │     │MessageHdlr│   │ knowledge │  │             │  │
│  │ send_resp│     │(TYPE_CHK) │   │ _tool     │  │             │  │
│  │          │     │           │   │create_    │  │             │  │
│  │BaseChannel│    │validate_  │   │ handoff_  │  │             │  │
│  │ get_conv()│    │ webhook   │   │ _tool     │  │             │  │
│  └──────────┘     └───────────┘   └───────────┘  └─────────────┘  │
│                                                                     │
│  Session          Models           Clients                          │
│  ┌──────────┐    ┌────────────┐   ┌────────────┐                   │
│  │SessionMgr│    │Conversation│   │MemoryClient│                   │
│  │ThreadSafe│    │  Session   │   │Knowledge   │                   │
│  │SessionMgr│    │TACMemory  │   │  Client    │                   │
│  │SessionSt │    │  Response  │   │Conversation│                   │
│  └──────────┘    └────────────┘   │  Client    │                   │
│                                   └────────────┘                   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Error Handling & Resilience

### Error boundary model

Errors in agent callbacks must never crash the server or leave a channel in a broken state. The general policy:

| Layer | Error behavior |
|---|---|
| `TACRoutes` (TAC) | Route handlers catch all exceptions, log them, and return appropriate HTTP responses (500 for unexpected errors, 200 for webhooks that must not be retried). WebSocket handlers catch exceptions and close the connection cleanly. |
| `AgentFrameworkBridge._handle_message()` (SDK) | Wraps the channel-specific handler (`_handle_voice_message` / `_handle_sms`) in a try/except. On error: logs the exception, sends a user-facing error message via the channel (e.g., "Sorry, something went wrong"), and ensures cleanup runs. |
| `_stream_response()` (SDK, voice) | If the agent throws mid-stream, the async generator catches the exception, logs it, and yields a spoken error message ("I'm having trouble, please try again"). The voice channel receives a clean end-of-stream. |
| `_handle_sms()` (SDK, SMS) | Runs in a try/except/finally. On error: sends a generic error SMS. In the finally block: always persists session state (MS Agent Framework) or runs cleanup (Strands). The finally block must not send a response if one was already sent — check a `responded` flag. |
| `create_agent()` factory | If the factory throws (e.g., missing credentials, model unavailable), the error propagates to `_handle_message()`, which applies the general policy above. For voice, this means the first utterance gets an error response; subsequent utterances retry agent creation. |
| TAC API calls (memory, knowledge) | TAC clients already handle errors gracefully — `retrieve_memory()` falls back from Memory to Maestro, knowledge search returns empty results on failure. SDKs should not add retry logic around TAC calls; TAC owns its own resilience. |

### What is NOT retried

- Agent execution: no automatic retry. A failed agent call returns an error to the user. Retrying risks duplicate side effects from tool calls.
- Session persistence (MS Agent Framework): background saves are fire-and-forget. If a save fails, it's logged but the conversation continues. The next utterance will re-save.
- WebSocket disconnections: if the Twilio WebSocket drops, the conversation is cleaned up. Twilio will establish a new connection if the call is still active.

---

## Startup Hooks & Async Initialization

### The problem

Some agent setup requires async work before the first request arrives — e.g., fetching knowledge base metadata (`fetch_knowledge_base_info()`), pre-warming model connections, or validating credentials. The current Azure SDK's `OmniChannelServer` accepts an `on_startup` async callback for this. The new architecture needs to handle this without adding lifecycle methods to `AgentFrameworkBridge` (which is a pure request processor).

### Where startup hooks live in each interface level

`AgentFrameworkBridge` does **not** accept a startup hook. It has no lifecycle — it processes requests, nothing more. Async initialization belongs to the layer that owns the server lifecycle:

| Interface level | How to run async initialization |
|---|---|
| **Interface 1 + `TACServer`** | Use `TACServer.app` (FastAPI) lifespan events. `TACServer` exposes the underlying FastAPI app, so developers use `@app.on_event("startup")` or the `lifespan` context manager. |
| **Interface 1 + custom ASGI** | Framework-native startup hooks (FastAPI lifespan, Starlette `on_startup`, etc.) |
| **Interface 2 (`RuntimeServer`)** | Cloud runtime's own startup mechanism: Foundry's `FoundryCBAgent` lifecycle, AgentCore's app startup. Or add routes to `RuntimeServer.app` before calling `start()`. |
| **Interface 3 (`OmniChannelServer`)** | Accepts an optional `on_startup` async callback, executed inside the runtime's startup lifecycle. |

### `OmniChannelServer` startup hook

`OmniChannelServer` is the convenience layer and the only interface that accepts a startup hook directly. It delegates to the runtime's startup mechanism:

```python
class OmniChannelServer:
    def __init__(
        self,
        tac: TAC,
        create_agent: ...,
        *,
        on_startup: Callable[[], Awaitable[None]] | None = None,
        ...
    ):
        self.on_startup = on_startup
        ...

    def start(self, **kwargs):
        # Startup hook is wired into the runtime's app lifecycle
        if self.on_startup:
            self.runtime.app.on_event("startup")(self.on_startup)
        self.runtime.start(**kwargs)
```

### Usage patterns

```python
# Interface 3: OmniChannelServer with startup hook
async def startup():
    global kb_info
    kb_info = await fetch_knowledge_base_info(tac, knowledge_base_id)

server = OmniChannelServer(
    tac=tac,
    create_agent=create_agent,
    on_startup=startup,
    ...
)
server.start()
```

```python
# Interface 1 + TACServer: use FastAPI lifespan directly
handler = AgentFrameworkBridge(tac=tac, create_agent=create_agent)
server = TACServer(tac=tac, voice_channel=handler.voice_channel, ...)

@asynccontextmanager
async def lifespan(app):
    # Async init here
    kb_info = await fetch_knowledge_base_info(tac, knowledge_base_id)
    yield

# Override the app's lifespan before starting
server.app.router.lifespan_context = lifespan
server.start()
```

```python
# Interface 1 + custom FastAPI: developer owns the app entirely
handler = AgentFrameworkBridge(tac=tac, create_agent=create_agent)

@asynccontextmanager
async def lifespan(app):
    kb_info = await fetch_knowledge_base_info(tac, knowledge_base_id)
    yield

app = FastAPI(lifespan=lifespan)
routes = TACRoutes(voice_channel=handler.voice_channel,
                   sms_channel=handler.sms_channel, tac=tac, config=handler.config)
app.post("/twiml")(routes.handle_twiml)
# ... mount other routes
```

### Why not put startup hooks on `AgentFrameworkBridge`

Adding lifecycle to the handler would mean it needs to know about its hosting context (is it FastAPI? Starlette? AgentCore?). It would also create ambiguity about when `on_startup` runs — before channel creation? After? The clean separation is: **handler = request processing**, **server = lifecycle**. The current Azure SDK's `OmniChannelServer.on_startup` pattern is correct in spirit — it just needs to be on the server layer, not the handler layer.

---

## What Gets Deleted from Partner SDKs

### ms-agent-framework-twilio-agent-connect-python (`tac_azure` -> `tac_ms_agent_framework`)

**Structural changes:**

| Removed | Replaced by |
|---|---|
| `OmniChannelServer` (current) | New `OmniChannelServer` composing `AgentFrameworkBridge` + `RuntimeServer` |
| `AgentFrameworkBridge` (current) | New `AgentFrameworkBridge` that creates channels internally |
| All route creation code | TAC's `TACRoutes` |
| Channel creation boilerplate | Internal to `AgentFrameworkBridge.__init__` |
| URL construction from `public_domain` | TAC's `TACRoutes` via `TACServerConfig` |
| Custom webhook validation logic | TAC's `TACRoutes.validate_webhooks` + `validate_twilio_webhook()` |
| `on_startup` callback on `OmniChannelServer` | Moved to new `OmniChannelServer.on_startup` (same behavior, cleaner layering) |
| `fastapi`, `uvicorn`, `websockets` as direct deps | Come via TAC's `[server]` extra |
| `truststore`, `python-dotenv` deps | App-level concerns |

**Bug fixes / cleanup resolved by new architecture:**

| Issue | Resolution |
|---|---|
| Placeholder tools (`create_flex_escalation_tool`, `create_messaging_tool`) that return hardcoded strings | Removed until properly implemented — avoids misleading developers |

### strands-twilio-agent-connect-python (`strands_communications_twilio` -> `tac_strands`)

**Structural changes:**

| Removed | Replaced by |
|---|---|
| `OmniChannelServer` (559 lines) | New `OmniChannelServer` composing `AgentFrameworkBridge` + `RuntimeServer` |
| `AgentFrameworkBridge` (current) | New `AgentFrameworkBridge` — no duplicate streaming/agent/cleanup |
| `ThreadSafeSessionManager(stream_generator=...)` | Incompatible with TAC HEAD — callback pattern instead |
| SMS webhook fabrication | TAC's `TACRoutes` + `SMSChannel` |
| `fastapi`, `uvicorn`, `websockets` as direct deps | Come via TAC |
| Tool helpers that bypass TAC (70+ lines each) | 5-line wrappers that delegate to TAC |

**Bug fixes / cleanup resolved by new architecture:**

| Issue | Resolution |
|---|---|
| `handle_message_ready` callback had wrong parameter order | Callback wired correctly in `AgentFrameworkBridge.__init__` with proper signature |
| `finally` block in SMS handler always sent error message (even on success) | New `_handle_sms` uses `responded` flag to prevent double-response |
| Hardcoded `+17205273223` phone number fallback | Removed — phone number comes from `TACConfig` exclusively |

---

## Dependency Structure

### ms-agent-framework-twilio-agent-connect-python `pyproject.toml`

```toml
[project]
name = "ms-agent-framework-twilio-agent-connect-python"
dependencies = [
    "agent-framework",
    "twilio-agent-connect",
]

[project.optional-dependencies]
azure = ["agent-framework-azure-ai", "azure-identity"]
foundry = [
    "azure-ai-agentserver-core>=1.0.0b16",
    "azure-ai-agentserver-agentframework>=1.0.0b16",
]
dev = ["ruff", "mypy", "pytest", "pytest-asyncio"]
```

No `fastapi`, `uvicorn`, `websockets`, `pydantic` — come via TAC. `RuntimeServer` requires `pip install ms-agent-framework-twilio-agent-connect-python[foundry]`. Users deploying with `TACServer` don't pull in Foundry packages.

### strands-twilio-agent-connect-python `pyproject.toml`

```toml
[project]
name = "strands-twilio-agent-connect-python"
dependencies = [
    "strands-agents>=1.22.0",
    "twilio-agent-connect",
]

[project.optional-dependencies]
agentcore = ["bedrock-agentcore>=1.2.0"]
dev = ["ruff", "mypy", "pytest", "pytest-asyncio"]
```

`RuntimeServer` requires `pip install strands-twilio-agent-connect-python[agentcore]`. Users deploying with `TACServer` don't pull in `bedrock-agentcore` or `boto3`.

### Import guard strategy

`RuntimeServer` in both SDKs uses deferred imports for cloud-specific packages. The cloud dependency is imported inside `__init__`, not at module level, so that importing the SDK package never fails:

```python
# tac_ms_agent_framework/runtime_server.py
class RuntimeServer:
    def __init__(self, omnichannel, foundry_agent):
        try:
            from azure.ai.agentserver.core import FoundryCBAgent  # noqa: F811
        except ImportError:
            raise ImportError(
                "RuntimeServer requires the 'foundry' extra. "
                "Install with: pip install ms-agent-framework-twilio-agent-connect-python[foundry]"
            ) from None
        ...
```

This ensures:
- `from tac_ms_agent_framework import AgentFrameworkBridge` works without Foundry installed.
- `from tac_ms_agent_framework import RuntimeServer` works (the class is importable).
- `RuntimeServer(...)` fails with a clear message if the extra is missing.

The same pattern applies to `tac_strands` with `bedrock-agentcore`.

---

## Interface Comparison Table

| | `AgentFrameworkBridge` | `RuntimeServer` | `OmniChannelServer` |
|---|---|---|---|
| What it is | TAC + agent fw bridge | Cloud runtime + TAC routes | Both combined |
| Owns channels | Yes (creates internally) | No (uses handler's) | Yes (via handler) |
| Creates routes (`TACRoutes`) | No — exposes channels for server to use | Yes (from handler's channels) | Yes (via runtime) |
| Wires TAC callbacks | Yes (all three: message, ended, interrupt) | No | Yes (via handler) |
| Webhook validation | No — server concern | Yes (via `TACRoutes.validate_webhooks`) | Yes (via runtime) |
| Startup hooks | No — pure request processor | Via `app` property | Yes (`on_startup` parameter) |
| Cloud dependency | None | Yes | Yes |
| Has `start()`/`stop()` | No — pure request processor | Yes | Yes |
| Same name both SDKs | Yes | Yes | Yes |
| MS Agent Framework-specific | `session_store`, `on_message` | `foundry_agent` | Both |
| Strands-specific | (none currently) | `**agentcore_kwargs` | `**agentcore_kwargs` |

---

## Concurrency Model

### Guarantees

`AgentFrameworkBridge` is designed for concurrent use across multiple conversations. TAC's channels are already concurrent — `VoiceChannel` handles multiple simultaneous WebSocket connections, and `SMSChannel` processes webhooks concurrently via async handlers.

### Per-conversation isolation

| Resource | Isolation mechanism |
|---|---|
| Voice agents (`_voice_agents` dict) | Keyed by `conversation_id`. Each conversation gets its own agent instance. No shared mutable state between conversations. |
| Voice sessions (`_voice_sessions` dict, MS Agent Framework) | Keyed by `conversation_id`. Agent sessions are per-conversation. |
| TAC's `_conversations` dict | Keyed by `conversation_id`. Managed by `BaseChannel`. |
| `ThreadSafeSessionManager` | Uses `asyncio.Lock` per session. Concurrent access to the same session (e.g., interrupt during streaming) is serialized. |

### Within a single conversation

- **Voice:** Utterances from the same call arrive sequentially on the WebSocket. However, an interrupt message can arrive while a streaming response is in-flight. `SessionManager` handles this by cancelling the active `stream_task` before processing the interrupt. This is the only concurrent-access scenario within a single conversation.
- **SMS:** Messages from the same conversation can arrive concurrently (e.g., user sends two messages in quick succession). Each message creates its own agent execution. SDKs should ensure `_handle_sms` is safe for overlapping calls to the same `conversation_id` — MS Agent Framework's `AgentSessionStore.load()`/`save()` serializes access if the store implementation is atomic; Strands' ephemeral agents have no shared state.

### What is NOT thread-safe

- The `_voice_agents` and `_voice_sessions` dicts are plain Python dicts, not `concurrent.futures`-safe. This is acceptable because all access happens on the asyncio event loop (single-threaded). If a future SDK needs multi-threaded access (e.g., background thread for cleanup), it must add its own locking.

---

## Observability

### Structured logging

All components use Python's `logging` module via TAC's `get_logger()`. Log messages include:

- `conversation_id` on all per-conversation log lines
- `channel` (`voice` / `sms`) on message handling logs
- `profile_id` where available
- Exception tracebacks on errors (via `logger.exception()`)

SDKs should use the same `get_logger(__name__)` pattern. This ensures log output is filterable by module (`tac.*`, `tac_ms_agent_framework.*`, `tac_strands.*`).

### OpenTelemetry

Tracing integration depends on the deployment layer:

| Deployment | Tracing source |
|---|---|
| `TACServer` (standalone) | No built-in tracing. Developers add OpenTelemetry middleware to `TACServer.app`. |
| `RuntimeServer` + Foundry | `FoundryCBAgent` provides OpenTelemetry auto-instrumentation, spans for `/responses`, `/liveness`, OAuth token refresh. TAC route handlers inherit the active trace context. |
| `RuntimeServer` + AgentCore | `BedrockAgentCoreApp` provides request context propagation and task tracking. TAC route handlers inherit the request context. |

`AgentFrameworkBridge` does not create its own spans or metrics — it delegates to whatever tracing is configured on the ASGI app. This avoids double-instrumentation and keeps the handler deployment-agnostic.

### Future considerations

- Per-conversation metrics (latency, token usage, error rate) can be added via TAC callbacks without changing the handler interface.
- Agent framework-level tracing (LLM call spans, tool execution spans) is owned by the frameworks themselves (Agent Framework, Strands) and is orthogonal to this architecture.

---

## Testing Strategy

### Three-level testing model

| Level | What it tests | Where it lives | Runs against |
|---|---|---|---|
| **TAC unit tests** | Channels, routes, tools, session management, memory fallback | `twilio-agent-connect-python/tests/` | Mocked Twilio APIs, mocked Memory/Maestro clients |
| **SDK unit tests** | Handler logic, streaming bridge, SMS execution, agent caching, tool conversion, session persistence | Each SDK's `tests/` directory | Mocked TAC objects, mocked agent frameworks |
| **Integration tests** | Full route → handler → agent → response flow | Each SDK's `tests/integration/` | Real `TACRoutes` + `AgentFrameworkBridge` with mock agents, real ASGI test client |

### Contract tests between TAC and SDKs

The `TACRoutes` class and `BaseChannel` callbacks form the contract surface between TAC and partner SDKs. To prevent regressions:

- TAC exports a `TACRoutes` test fixture that SDKs import in their integration tests. This fixture creates a `TACRoutes` instance with mock channels and verifies that route handlers call the expected channel methods with the expected arguments.
- The `MessageHandler` protocol (in `TYPE_CHECKING`) is validated by `mypy` / `pyright` in each SDK's CI — if the handler's callback signatures drift from the protocol, the type checker catches it.

### SDK unit test patterns

```python
# Test that AgentFrameworkBridge wires callbacks correctly
def test_handler_wires_callbacks():
    mock_tac = Mock(spec=TAC)
    handler = AgentFrameworkBridge(tac=mock_tac, create_agent=mock_factory)
    mock_tac.on_message_ready.assert_called_once()
    mock_tac.on_conversation_ended.assert_called_once()

# Test that _stream_response yields agent chunks
async def test_stream_response_yields_chunks():
    handler = AgentFrameworkBridge(tac=mock_tac, create_agent=mock_factory)
    chunks = [chunk async for chunk in handler._stream_response("hello", session)]
    assert chunks == ["Hi", " there"]

# Test that RuntimeServer mounts all expected routes
def test_runtime_server_mounts_routes():
    handler = AgentFrameworkBridge(tac=mock_tac, create_agent=mock_factory)
    server = RuntimeServer(omnichannel=handler, **mock_kwargs)
    route_paths = [r.path for r in server.app.routes]
    assert "/twiml" in route_paths
    assert "/ws" in route_paths
```

### CI requirements

Both SDKs require in CI: `ruff` (linting), `mypy --strict` (type checking), `pytest` (unit + integration), `pytest-asyncio` (async test support). Coverage targets should be set per-SDK — at minimum, all handler methods and tool factories must have test coverage.

---

## Migration & Versioning

### Package renames

| Current | New | Python import |
|---|---|---|
| `azure-twilio-agent-connect-python` (import: `tac_azure`) | `ms-agent-framework-twilio-agent-connect-python` | `tac_ms_agent_framework` |
| `strands-communications-twilio` (import: `strands_communications_twilio`) | `strands-twilio-agent-connect-python` | `tac_strands` |

These are breaking changes. Both SDKs are currently pre-1.0 and have no external consumers beyond internal teams, so this is the right time to rename.

### Versioning strategy

- **TAC**: The new `TACRoutes`, `get_conversation()`, and `MessageHandler` protocol are additive. `TACServer` is refactored but its constructor signature is unchanged. This is a **minor version bump** (e.g., `0.x.0` → `0.x+1.0`).
- **Partner SDKs**: The renames, restructured exports, and changed `create_agent` factory signature (`(conversation_id, profile_id)` → `ConversationSession`) are breaking. Both SDKs publish their first release under the new package name at **`0.1.0`**. The old package names are not re-published — they are archived.

### Migration steps for existing users

1. **Update imports**: `from tac_azure import ...` → `from tac_ms_agent_framework import ...` (or `tac_strands`).
2. **Update `create_agent` factory**: Change `def create_agent(conversation_id, profile_id)` → `def create_agent(session: ConversationSession)`. Access IDs via `session.conversation_id`, `session.profile_id`. Access new context via `session.channel`, `session.profile`, `session.metadata`.
3. **Remove `handler.start()`**: If using Interface 1 standalone, wrap the handler in `TACServer` (see updated usage example).
4. **Update tool imports**: `from tac_azure.tools import ...` → `from tac_ms_agent_framework.tools import ...`.
5. **Update `pyproject.toml`**: Change dependency name and add extras if using `RuntimeServer`.
