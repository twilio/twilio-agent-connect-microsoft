# Architecture Proposal: TAC + Partner SDKs

## What This Proposal Solves

Clear ownership boundaries between TAC and its partner SDKs (`tac-azure`, `strands-communications-twilio`). Today both SDKs duplicate TAC's server, channels, and routing — reimplementing what TAC already provides. This proposal defines who owns what.

### The target architecture

**TAC** owns everything Twilio-specific:
- `TACServer` — deploy-it-yourself FastAPI server with all Twilio routes
- `TACRoutes` — framework-agnostic route handlers (Starlette types) that any server can mount
- `MessageHandler` protocol — the interface partner SDKs implement
- Channels, tools, session management, memory, knowledge

**Partner handler** (in the partner package) bridges the partner's agent framework with TAC:
- `AgentFrameworkHandler` — bridges Microsoft Agent Framework with TAC's callback system
- `StrandsHandler` — bridges Strands Agents with TAC's callback system
- Owns: agent creation, voice streaming, SMS execution, session persistence, cleanup

**Partner server** (in the partner package) bridges the partner's managed cloud runtime with TAC:
- `FoundryServer` — mounts `TACRoutes` on Azure Foundry Agent Service (`FoundryCBAgent`)
- `AgentCoreServer` — mounts `TACRoutes` on AWS Bedrock AgentCore (`BedrockAgentCoreApp`)
- These are thin wrappers. The route logic lives in TAC. The partner server just picks which runtime to mount it on.

### How it works for users

| I want to... | I use... |
|---|---|
| Deploy my own server (any framework) | `TACServer` + register `on_message_ready` yourself |
| Use Strands SDK with my own server | `StrandsHandler` + `TACServer` |
| Use Agent Framework SDK with my own server | `AgentFrameworkHandler` + `TACServer` |
| Deploy Strands agent to Bedrock AgentCore | `StrandsHandler` + `AgentCoreServer` |
| Deploy Agent Framework agent to Foundry | `AgentFrameworkHandler` + `FoundryServer` |

---

## The Problem Today

Both partner SDKs duplicate work that TAC already does. They each independently:

- Create `VoiceChannel` and `SMSChannel` instances internally
- Build a server with TwiML, WebSocket, SMS, and callback routes
- Construct WebSocket/callback URLs from `public_domain`
- Pass through `handle_websocket()`, `handle_incoming_call()`, `process_webhook()` calls

Meanwhile, TAC already has `TACServer` which does all of this. The SDKs re-wrap TAC's server layer instead of complementing it. Everything they duplicate is redundant.

---

## Current State

### What each SDK contains today

| Component | tac-azure | strands | TAC |
|---|---|---|---|
| Server + routes | `OmniChannelServer` (266 lines, FastAPI) | `OmniChannelServer` (559 lines, FastAPI) | `TACServer` (~130 lines, FastAPI) |
| Channel creation | In `AgentFrameworkConnector.__init__` | In both handler and server | User creates, passes to `TACServer` |
| Voice streaming bridge | `_stream_response()` — `agent.run(stream=True)` → `AsyncGenerator` | `_stream_strands_response()` — `agent.stream_async()` → parse Bedrock events → `yield` | N/A — framework-specific |
| Agent lifecycle | `_get_or_create_voice_agent`, `_voice_agents` dict | Same pattern, identical code | N/A — framework-specific |
| Agent session persistence | `AgentSessionStore` protocol + load/save around `agent.run()` | None (ephemeral agents) | N/A — framework-specific |
| SMS agent execution | `_handle_sms_message()` — load session → `agent.run()` → send → save | `handle_message_ready()` — create agent → `agent.run_async()` → parse → send | N/A — framework-specific |
| Tool wrappers | `create_memory_recall_tool()`, `create_knowledge_tool()` | `create_memory_recall_tool()`, `create_knowledge_tool()` | `create_memory_tool()`, `create_knowledge_tool()` |
| Memory prompt formatting | `format_memory_context()` | N/A (uses tool only) | `TACMemoryResponse.build_memory_prompts()` |
| Webhook signature validation | In `OmniChannelServer` | None | `validate_twilio_webhook()` exists but `TACServer` doesn't use it |
| Agent proxy abstraction | None needed — `Agent` has a clean API | `AgentProxy` ABC (local + remote) | N/A |

### The duplication problem

**Strands:** `OmniChannelServer` and `AgentFrameworkConnector` are independent implementations with no shared base class. Both create channels, implement `_stream_strands_response()`, `_get_or_create_voice_agent()`, `_cleanup_voice_agent()`, and `handle_twiml_request()`. ~200 lines of identical code between the two files.

**tac-azure:** Fixed the handler/server duplication (server composes handler), but `AgentFrameworkConnector` still duplicates TAC's channel creation and URL construction. Its public methods (`handle_twiml_request`, `handle_websocket_connection`, `handle_sms_webhook`) are 1:1 pass-throughs to TAC channel methods.

### Both access private TAC internals

Both SDKs read `self.voice_channel._conversations[conversation_id]` to get the `ConversationSession` for agent creation. `BaseChannel._conversations` is a private dict with no public getter. Any TAC refactor breaks both SDKs silently.

### Strands is pinned to an old TAC commit

The Strands SDK imports `ThreadSafeSessionManager` from `tac.channels.session_manager` (old path) and passes `stream_generator` to its constructor — a parameter that no longer exists in TAC HEAD. TAC HEAD's `ThreadSafeSessionManager` lives at `tac.session` and takes no constructor arguments. The tac-azure SDK already uses the new pattern (callback-based via `on_message_ready`, calling `voice_channel.send_response()` with a generator). The Strands SDK must migrate to this pattern regardless.

### Strands SMS webhook format mismatch

The Strands `OmniChannelServer.handle_sms_webhook()` fabricates Twilio Conversations API events from raw SMS webhooks:

```python
webhook_data = {
    "EventType": "onMessageAdded",
    "ConversationSid": from_number,  # not a real conversation SID
    "Body": body,
    "Author": from_number,
    "MessageSid": message_sid,
}
```

TAC's `SMSChannel.process_webhook()` expects real Conversations API format. This translation layer needs to be addressed — either TAC supports raw SMS natively, or the adapter keeps the translation.

### Strands has a bug in handle_message_ready

The `finally` block in `server.py:546-558` unconditionally sends an error message after every SMS, not just on failure:

```python
finally:
    agent.cleanup()
    del agent
    error_msg = "I apologize, but I encountered an error. Please try again."
    await self.sms_channel.send_response(conversation_id, error_msg, role="assistant")
```

---

## Proposed Architecture

### Three layers

```
┌────────────────────────────────────────────────────────────────┐
│  Layer 3: Server Wrappers (mount TACRoutes on a framework)     │
│  TACServer (FastAPI)           │  AgentCoreServer              │
│  both SDKs / deploy anywhere  │  tac-strands / AWS Bedrock    │
├────────────────────────────────────────────────────────────────┤
│  Layer 2: Agent Handlers (implement MessageHandler)            │
│  AgentFrameworkHandler (Azure)  │  StrandsHandler (AWS)        │
├────────────────────────────────────────────────────────────────┤
│  Layer 1: TAC (channels, routes, tools, protocols)             │
│  VoiceChannel, SMSChannel, TACRoutes, MessageHandler           │
└────────────────────────────────────────────────────────────────┘
```

### No cloud lock-in

The handler (Layer 2) is the core of each SDK. It has **zero cloud platform dependencies** — only the agent framework and TAC:

```
pip install tac-agent-framework       # deps: agent-framework + tac
pip install tac-strands                # deps: strands-agents + tac
```

With just the base install, you can build a full omnichannel agent and deploy it anywhere — a VM, Docker, Railway, Fly.io, Lambda behind API Gateway, or any host that can run a Python process. You use `TACServer` (from TAC, FastAPI-based) as your server and you're done. No AWS, no Azure, no cloud SDK in your dependency tree.

Cloud deployment extras are optional:

```
pip install tac-agent-framework[foundry]   # adds FoundryServer (Azure Foundry Agent Service)
pip install tac-strands[agentcore]         # adds AgentCoreServer (AWS Bedrock AgentCore)
```

### SDK symmetry

Both SDKs have the same shape — a handler (always included) + optional cloud server:

| | tac-strands | tac-agent-framework |
|---|---|---|
| Agent framework | Strands Agents | Microsoft Agent Framework |
| Handler (Layer 2) | `StrandsHandler` | `AgentFrameworkHandler` |
| Deploy anywhere | `TACServer` (from TAC) | `TACServer` (from TAC) |
| Deploy to managed cloud | `AgentCoreServer` (optional) | `FoundryServer` (optional) |
| Cloud runtime | AWS Bedrock AgentCore | Azure Foundry Agent Service |
| Cloud dependency | `bedrock-agentcore` (optional) | `azure-ai-agentserver-core` (optional) |

The handler works identically regardless of which server hosts it. Switching from `TACServer` to `AgentCoreServer` or `FoundryServer` is a one-line change with no handler modifications.

### Layer 1: TAC

TAC is the foundation. It owns everything Twilio-specific:

- **Channels:** `VoiceChannel`, `SMSChannel` — protocol handling, WebSocket lifecycle, webhook processing
- **Route handlers:** `TACRoutes` — framework-agnostic Starlette request handlers (NEW)
- **Server:** `TACServer` — mounts `TACRoutes` on FastAPI
- **Protocol:** `MessageHandler` — the interface agent framework SDKs implement (NEW)
- **Tools:** memory, knowledge, handoff primitives
- **Session:** `ConversationSession`, `SessionManager`, `ThreadSafeSessionManager`
- **Clients:** memory, knowledge, conversation (Maestro)

### Layer 2: Agent Framework Handlers

Each SDK provides a class implementing `MessageHandler`. The handler owns:

- Agent creation via a user-provided factory
- Voice agent caching (per-call reuse) and cleanup
- Streaming bridge (framework-specific events → `AsyncGenerator[str]` → `voice_channel.send_response()`)
- SMS agent execution (`agent.run()` → `sms_channel.send_response()`)
- Channel-based dispatch (`context.channel == "voice"` vs `"sms"`)
- Agent session/history persistence (framework-specific)
- Error handling and fallback responses

The handler **does not** create channels, build routes, construct URLs, or host a server.

### Layer 3: Server Wrappers

Thin wrappers that mount `TACRoutes` on a specific web framework:

- **`TACServer`** (in TAC) — mounts on FastAPI. For local dev, self-hosted production, and any platform-agnostic deployment. Used by both SDKs.
- **`AgentCoreServer`** (in tac-strands) — mounts on `BedrockAgentCoreApp` (Starlette). For Bedrock AgentCore managed deployment. Gets `/invocations`, `/ping`, task tracking, request context propagation.
- **`FoundryServer`** (in tac-agent-framework) — mounts on `FoundryCBAgent` (Starlette). For Azure Foundry Agent Service deployment. Gets `POST /responses`, `/liveness`, `/readiness`, conversation persistence, OpenTelemetry, OAuth consent.

All three accept channels and a `MessageHandler` via the same interface. The handler is **composed into** the server — no dangling variables, no `__init__` side effects.

---

## Changes Required in TAC

### 1. `MessageHandler` protocol

**Problem:** Both SDKs implement the same callback pattern but there's no shared interface. The adapters register callbacks as `__init__` side effects, producing variables that are never referenced after construction.

**Solution:** TAC defines a protocol that agent framework SDKs implement:

```python
# tac/protocols.py

from typing import Protocol, runtime_checkable
from tac.models.session import ConversationSession
from tac.models.tac import TACMemoryResponse


@runtime_checkable
class MessageHandler(Protocol):
    """Protocol that agent framework adapters implement."""

    async def handle_message(
        self,
        user_message: str,
        context: ConversationSession,
        memory: TACMemoryResponse | None,
    ) -> None: ...

    async def handle_conversation_ended(
        self,
        context: ConversationSession,
    ) -> None: ...
```

Server wrappers accept a `MessageHandler` and wire it to TAC's callback system explicitly. No hidden registration.

### 2. `TACRoutes` — framework-agnostic route handlers

**Problem:** `TACServer` creates FastAPI-specific route handlers. The Strands SDK needs the same route logic mounted on `BedrockAgentCoreApp` (Starlette). Both are Starlette underneath, but there's no way to reuse the route logic without duplicating it.

**Solution:** Extract route handlers into a class that uses Starlette types (`Request`, `Response`, `WebSocket`), compatible with any ASGI framework:

```python
# tac/server/routes.py

import asyncio
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.websockets import WebSocket


class TACRoutes:
    """Framework-agnostic route handlers for TAC channels.

    Uses Starlette types (Request, Response, WebSocket), which are
    compatible with FastAPI, BedrockAgentCoreApp, and any ASGI
    framework built on Starlette.
    """

    def __init__(self, voice_channel=None, sms_channel=None, config=None):
        self.voice_channel = voice_channel
        self.sms_channel = sms_channel
        self.config = config or TACServerConfig.from_env()

    async def handle_twiml(self, request: Request) -> Response:
        form = await request.form()
        ws_url = f"wss://{self.config.public_domain}{self.config.websocket_path}"
        action_url = (
            self.config.handoff_url
            or f"https://{self.config.public_domain}{self.config.conversation_relay_callback_path}"
        )
        twiml = await self.voice_channel.handle_incoming_call(
            to_number=str(form["To"]),
            from_number=str(form["From"]),
            options={
                "websocket_url": ws_url,
                "action_url": action_url,
                "welcome_greeting": self.config.welcome_greeting,
            },
            call_sid=str(form["CallSid"]),
        )
        return Response(content=twiml, media_type="application/xml")

    async def handle_websocket(self, websocket: WebSocket) -> None:
        adapter = FastAPIWebSocketAdapter(websocket)
        await self.voice_channel.handle_websocket(adapter)

    async def handle_sms_webhook(self, request: Request) -> JSONResponse:
        form_data = await request.json()
        token = request.headers.get("i-twilio-idempotency-token")
        asyncio.create_task(
            self.sms_channel.process_webhook(dict(form_data), token)
        )
        return JSONResponse(content={"status": "ok"}, status_code=200)

    async def handle_conversation_relay_callback(self, request: Request) -> Response:
        form = await request.form()
        payload_dict = {k: str(v) for k, v in form.items()}
        result = await self.voice_channel.handle_conversation_relay_callback(payload_dict)
        if result is not None:
            return Response(content=result, media_type="text/xml")
        return Response(content="OK", media_type="text/plain")
```

`TACServer` becomes a thin wrapper that mounts these on FastAPI. Agent framework SDKs can mount them on their own framework (e.g., `BedrockAgentCoreApp`).

### 3. Public getter for `ConversationSession`

**Problem:** Both SDKs access `voice_channel._conversations[conversation_id]`.

**Solution:**

```python
class BaseChannel:
    def get_conversation(self, conversation_id: str) -> ConversationSession | None:
        """Get the ConversationSession for an active conversation."""
        return self._conversations.get(conversation_id)
```

### 4. `TACServer` accepts `MessageHandler`

**Problem:** No way to compose a handler into the server. Handlers register callbacks as constructor side effects, producing unused variables.

**Solution:** `TACServer` wires the handler to TAC's callback system:

```python
class TACServer:
    def __init__(
        self,
        tac: TAC,
        voice_channel: VoiceChannel | None = None,
        sms_channel: SMSChannel | None = None,
        message_handler: MessageHandler | None = None,
        config: TACServerConfig | None = None,
        on_startup: Callable[[], Awaitable[None]] | None = None,
        validate_webhooks: bool = False,
    ):
        self.tac = tac
        self.config = config or TACServerConfig.from_env()
        self.routes = TACRoutes(
            voice_channel=voice_channel,
            sms_channel=sms_channel,
            config=self.config,
        )
        self.on_startup = on_startup
        self.validate_webhooks = validate_webhooks
        self._app = None
        self._server = None

        # Compose handler — explicit wiring, no side effects
        if message_handler is not None:
            tac.on_message_ready(message_handler.handle_message)
            tac.on_conversation_ended(message_handler.handle_conversation_ended)

    @property
    def app(self) -> FastAPI:
        if self._app is None:
            self._app = self._create_app()
        return self._app

    def _create_app(self) -> FastAPI:
        app = FastAPI(title="TAC Server")
        r = self.routes
        c = self.config

        if r.sms_channel is not None:
            app.post(c.sms_webhook_path)(r.handle_sms_webhook)
        if r.voice_channel is not None:
            app.post(c.twiml_path)(r.handle_twiml)
            app.websocket(c.websocket_path)(r.handle_websocket)
            app.post(c.conversation_relay_callback_path)(r.handle_conversation_relay_callback)

        app.get("/health")(lambda: {"status": "ok"})
        return app

    async def serve_async(self) -> None:
        config = uvicorn.Config(self.app, host=self.config.host, port=self.config.port)
        self._server = uvicorn.Server(config)
        await self._server.serve()

    def stop(self) -> None:
        if self._server:
            self._server.should_exit = True

    def start(self) -> None:
        uvicorn.run(self.app, host=self.config.host, port=self.config.port)
```

### 5. Webhook signature validation

**Problem:** `TACServer` has no signature validation. `tac-azure` added it in `OmniChannelServer`.

**Solution:** Add `validate_webhooks: bool` to `TACServer` and validation logic in route handlers. TAC already has the `validate_twilio_webhook()` utility.

### 6. Summary of TAC changes

| Change | Effort | Impact |
|---|---|---|
| `MessageHandler` protocol | Small | Clean composition, swappable handlers |
| `TACRoutes` (framework-agnostic) | Medium | Enables AgentCore and Foundry deployment without route duplication |
| `BaseChannel.get_conversation()` | Small | Eliminates private access in both SDKs |
| `TACServer` accepts `MessageHandler` | Small | Composable handler wiring, no dangling variables |
| Lazy `app` property on `TACServer` | Small | Enables middleware/customization |
| `serve_async()` / `stop()` | Small | Programmatic server control |
| `on_startup` hook | Small | Enables async init without custom server |
| `validate_webhooks` | Medium | Security default for all users |
| `/health` route | Trivial | Standard server endpoint |

---

## What Each SDK Becomes

### `tac-azure` → `tac-agent-framework`

**~300 lines of focused code.** Contains:

1. **`AgentFrameworkHandler`** — implements `MessageHandler`
   - `handle_message()` — dispatches by `context.channel`
   - `handle_conversation_ended()` — cleans up voice agent/session
   - `_handle_voice()` — feeds streaming generator into `voice_channel.send_response()`
   - `_handle_sms()` — load session → augment → `agent.run()` → send → save
   - `_stream_response()` — `agent.run(stream=True)` → `AsyncGenerator[str]`
   - `_get_or_create_voice_agent()` — per-call agent caching via `voice_channel.get_conversation()`
   - `_cleanup_voice_agent()` — cleanup on disconnect
   - `_background_save_session()` — fire-and-forget voice session persistence

2. **`AgentSessionStore`** — protocol for pluggable session persistence
   - `load(session_id) -> AgentSession | None`
   - `save(session_id, session) -> None`
   - `InMemoryAgentSessionStore` — default implementation

3. **`format_memory_context()`** — composes `TACMemoryResponse` data with user message into an augmented prompt string. Uses TAC's `build_memory_prompts()` internally.

4. **Tool bridge helpers** — thin wrappers that extract `tac_tool.implementation` for Agent Framework's tools list. Absorb TAC tool API changes so user code doesn't break.

5. **`FoundryServer`** — mounts `TACRoutes` on `FoundryCBAgent`
   - Provides `POST /responses`, `/liveness`, `/readiness`, conversation persistence, OpenTelemetry, OAuth consent
   - Required for Azure Foundry Agent Service deployment
   - Same `message_handler` composition pattern as `TACServer`

**Removed:**
- `OmniChannelServer` — use `TACServer` or `FoundryServer`
- `AgentFrameworkConnector` public route methods — handler works through `MessageHandler`
- Placeholder tools (flex, messaging) — remove until implemented
- `truststore`, `python-dotenv` dependencies — app-level concerns

### `strands-communications-twilio` → `tac-strands`

**~300 lines of focused code.** Contains:

1. **`StrandsHandler`** — implements `MessageHandler`
   - `handle_message()` — dispatches by `context.channel`
   - `handle_conversation_ended()` — cleans up voice agent
   - `_handle_voice()` — feeds streaming generator into `voice_channel.send_response()`
   - `_handle_sms()` — create ephemeral agent → `agent.run_async()` → parse Bedrock response → send → cleanup
   - `_stream_strands_response()` — `agent.stream_async()` → parse `contentBlockDelta` events → `yield str`
   - `_get_or_create_voice_agent()` — per-call agent caching via `voice_channel.get_conversation()`
   - `_cleanup_voice_agent()` — cleanup with `agent.cleanup()`

2. **`AgentCoreServer`** — mounts `TACRoutes` on `BedrockAgentCoreApp`
   - Provides `/invocations`, `/ping`, task tracking, request context propagation
   - Required for Bedrock AgentCore managed deployment
   - Same `message_handler` composition pattern as `TACServer`

3. **`AgentProxy`** — ABC for local vs remote execution
   - `LocalAgentProxy` — wraps Strands `Agent`
   - `RemoteAgentProxy` — wraps Bedrock AgentCore runtime client

4. **Tool bridge helpers** — same pattern as tac-azure

**Removed:**
- `OmniChannelServer` — use `TACServer` or `AgentCoreServer`
- `AgentFrameworkConnector` — replaced by `StrandsHandler`
- Duplicated streaming/agent/cleanup code between handler and server
- Fabricated SMS webhook translation (needs resolution — see Open Questions)

---

## Why the Partner Servers Exist (and Why `TACServer` Isn't Enough)

Both AWS and Azure have managed agent runtimes that are Starlette-based but add platform-specific infrastructure. You can't replace them with `TACServer`.

### `BedrockAgentCoreApp` (AWS)

`BedrockAgentCoreApp` extends Starlette and adds:

| Feature | TACServer (FastAPI) | BedrockAgentCoreApp |
|---|---|---|
| Agent invocation | None | `POST /invocations` |
| Health check | `/health` (basic) | `/ping` (HEALTHY/HEALTHY_BUSY) |
| `@app.entrypoint` | No | Yes — registers main agent handler |
| `@app.async_task` | No | Yes — tracks active tasks for auto ping status |
| Request context | No | Session IDs, access tokens via `BedrockAgentCoreContext` |
| Worker loop isolation | No | Handler runs on background thread so `/ping` stays responsive |

Strands users deploying to Bedrock AgentCore **must** use `BedrockAgentCoreApp`. `AgentCoreServer` mounts `TACRoutes` onto it.

### `FoundryCBAgent` (Azure)

`FoundryCBAgent` from `azure-ai-agentserver-core` creates a Starlette app and adds:

| Feature | TACServer (FastAPI) | FoundryCBAgent |
|---|---|---|
| Agent invocation | None | `POST /responses` (OpenAI Responses API format) |
| Health checks | `/health` (basic) | `/liveness` + `/readiness` |
| Request context | None | Conversation ID, response ID, agent metadata, tracing context |
| Conversation persistence | None | Auto-saves input/output to Foundry conversation store |
| Session management | None | `AgentSessionRepository` + Foundry history providers |
| Observability | None | Auto OTLP + Application Insights exporters |
| Auth flows | None | Built-in OAuth consent flow |
| Streaming | None | SSE with keep-alive, error events, metadata attachment |
| Agent adapter | None | `from_agent_framework(agent)` one-liner wrapper |

Agent Framework users deploying to Foundry Agent Service **must** use `FoundryCBAgent`. `FoundryServer` mounts `TACRoutes` onto it.

### Both are Starlette underneath

Since FastAPI, `BedrockAgentCoreApp`, and `FoundryCBAgent` all build on Starlette, they share the same `Request`/`Response`/`WebSocket` types. `TACRoutes` uses these types, so the same route handlers work on any of the three with zero adaptation.

### `AgentCoreServer` implementation

```python
# tac_strands/agentcore_server.py

from bedrock_agentcore import BedrockAgentCoreApp
from tac.server.routes import TACRoutes
from tac.server.config import TACServerConfig


class AgentCoreServer:
    """Mounts TAC routes on BedrockAgentCoreApp."""

    def __init__(self, tac, voice_channel=None, sms_channel=None,
                 message_handler=None, config=None, **agentcore_kwargs):
        self.config = config or TACServerConfig.from_env()
        self.routes = TACRoutes(voice_channel=voice_channel, sms_channel=sms_channel,
                                config=self.config)
        if message_handler is not None:
            tac.on_message_ready(message_handler.handle_message)
            tac.on_conversation_ended(message_handler.handle_conversation_ended)
        self.app = self._create_app(**agentcore_kwargs)

    def _create_app(self, **agentcore_kwargs) -> BedrockAgentCoreApp:
        app = BedrockAgentCoreApp(**agentcore_kwargs)
        r, c = self.routes, self.config
        if r.voice_channel is not None:
            app.add_route(c.twiml_path, r.handle_twiml, methods=["POST"])
            app.add_websocket_route(c.websocket_path, r.handle_websocket)
            app.add_route(c.conversation_relay_callback_path, r.handle_conversation_relay_callback, methods=["POST"])
        if r.sms_channel is not None:
            app.add_route(c.sms_webhook_path, r.handle_sms_webhook, methods=["POST"])
        return app

    def start(self, host="0.0.0.0", port=8080):
        self.app.run(host=host, port=port)
```

### `FoundryServer` implementation

```python
# tac_agent_framework/foundry_server.py

from starlette.routing import Route, WebSocketRoute
from azure.ai.agentserver.core import FoundryCBAgent
from tac.server.routes import TACRoutes
from tac.server.config import TACServerConfig


class FoundryServer:
    """Mounts TAC routes on FoundryCBAgent's Starlette app."""

    def __init__(self, tac, voice_channel=None, sms_channel=None,
                 message_handler=None, config=None, foundry_agent=None, **foundry_kwargs):
        self.config = config or TACServerConfig.from_env()
        self.routes = TACRoutes(voice_channel=voice_channel, sms_channel=sms_channel,
                                config=self.config)
        if message_handler is not None:
            tac.on_message_ready(message_handler.handle_message)
            tac.on_conversation_ended(message_handler.handle_conversation_ended)
        self.agent = foundry_agent or FoundryCBAgent(**foundry_kwargs)
        self._mount_tac_routes()

    def _mount_tac_routes(self):
        r, c = self.routes, self.config
        new_routes = []
        if r.voice_channel is not None:
            new_routes.append(Route(c.twiml_path, r.handle_twiml, methods=["POST"]))
            new_routes.append(WebSocketRoute(c.websocket_path, r.handle_websocket))
            new_routes.append(Route(c.conversation_relay_callback_path, r.handle_conversation_relay_callback, methods=["POST"]))
        if r.sms_channel is not None:
            new_routes.append(Route(c.sms_webhook_path, r.handle_sms_webhook, methods=["POST"]))
        self.agent.app.routes.extend(new_routes)

    @property
    def app(self):
        return self.agent.app

    def start(self, port=8088):
        self.agent.run(port=port)
```

---

## What This Looks Like In Practice

### Microsoft Agent Framework + FastAPI (local dev)

```python
from tac import TAC, TACConfig
from tac.channels.voice import VoiceChannel
from tac.channels.sms import SMSChannel
from tac.server import TACServer
from tac.session import ThreadSafeSessionManager
from tac_agent_framework import AgentFrameworkHandler

tac = TAC(config=TACConfig.from_env())
voice = VoiceChannel(tac, session_manager=ThreadSafeSessionManager())
sms = SMSChannel(tac)

server = TACServer(
    tac=tac,
    voice_channel=voice,
    sms_channel=sms,
    message_handler=AgentFrameworkHandler(
        voice_channel=voice,
        sms_channel=sms,
        create_agent=create_agent,
    ),
)
server.start()
```

### Microsoft Agent Framework + Foundry Agent Service (Azure deployment)

```python
from tac import TAC, TACConfig
from tac.channels.voice import VoiceChannel
from tac.channels.sms import SMSChannel
from tac.session import ThreadSafeSessionManager
from tac_agent_framework import AgentFrameworkHandler, FoundryServer

tac = TAC(config=TACConfig.from_env())
voice = VoiceChannel(tac, session_manager=ThreadSafeSessionManager())
sms = SMSChannel(tac)

server = FoundryServer(
    tac=tac,
    voice_channel=voice,
    sms_channel=sms,
    message_handler=AgentFrameworkHandler(
        voice_channel=voice,
        sms_channel=sms,
        create_agent=create_agent,
    ),
    foundry_agent=from_agent_framework(my_agent),
)
server.start()
```

### Strands + Bedrock AgentCore (AWS deployment)

```python
from tac import TAC, TACConfig
from tac.channels.voice import VoiceChannel
from tac.channels.sms import SMSChannel
from tac.session import ThreadSafeSessionManager
from tac_strands import StrandsHandler, AgentCoreServer

tac = TAC(config=TACConfig.from_env())
voice = VoiceChannel(tac, session_manager=ThreadSafeSessionManager())
sms = SMSChannel(tac)

server = AgentCoreServer(
    tac=tac,
    voice_channel=voice,
    sms_channel=sms,
    message_handler=StrandsHandler(
        voice_channel=voice,
        sms_channel=sms,
        agent_factory=agent_factory,
    ),
)
server.start()
```

### Strands + FastAPI (local dev)

```python
from tac import TAC, TACConfig
from tac.channels.voice import VoiceChannel
from tac.channels.sms import SMSChannel
from tac.server import TACServer
from tac.session import ThreadSafeSessionManager
from tac_strands import StrandsHandler

tac = TAC(config=TACConfig.from_env())
voice = VoiceChannel(tac, session_manager=ThreadSafeSessionManager())
sms = SMSChannel(tac)

server = TACServer(
    tac=tac,
    voice_channel=voice,
    sms_channel=sms,
    message_handler=StrandsHandler(
        voice_channel=voice,
        sms_channel=sms,
        agent_factory=agent_factory,
    ),
)
server.start()
```

### Custom BedrockAgentCoreApp (full control)

```python
from tac import TAC, TACConfig
from tac.channels.voice import VoiceChannel
from tac.channels.sms import SMSChannel
from tac.server.routes import TACRoutes
from tac.session import ThreadSafeSessionManager
from tac_strands import StrandsHandler
from bedrock_agentcore import BedrockAgentCoreApp

tac = TAC(config=TACConfig.from_env())
voice = VoiceChannel(tac, session_manager=ThreadSafeSessionManager())
sms = SMSChannel(tac)

# Handler — explicit wiring when not using a server wrapper
handler = StrandsHandler(voice_channel=voice, sms_channel=sms, agent_factory=agent_factory)
tac.on_message_ready(handler.handle_message)
tac.on_conversation_ended(handler.handle_conversation_ended)

# Reusable route handlers
routes = TACRoutes(voice_channel=voice, sms_channel=sms)

# Your own BedrockAgentCoreApp
app = BedrockAgentCoreApp()
app.add_route("/twiml", routes.handle_twiml, methods=["POST"])
app.add_websocket_route("/ws", routes.handle_websocket)
app.add_route("/webhook", routes.handle_sms_webhook, methods=["POST"])
app.add_route("/conversation-relay-callback", routes.handle_conversation_relay_callback, methods=["POST"])

@app.entrypoint
async def invoke(payload):
    # Your Bedrock AgentCore invocation logic
    ...

app.run()
```

### Swappable handlers (the payoff of composability)

```python
# Swap agent frameworks by changing one line
if USE_AZURE:
    handler = AgentFrameworkHandler(
        voice_channel=voice, sms_channel=sms, create_agent=create_af_agent,
    )
else:
    handler = StrandsHandler(
        voice_channel=voice, sms_channel=sms, agent_factory=create_strands_agent,
    )

server = TACServer(tac=tac, voice_channel=voice, sms_channel=sms, message_handler=handler)
server.start()
```

### Same handler, different deployment targets

```python
# Same TAC primitives, same handler — only the server wrapper changes
tac = TAC(config=TACConfig.from_env())
voice = VoiceChannel(tac, session_manager=ThreadSafeSessionManager())
sms = SMSChannel(tac)

# The handler is identical across all deployment targets
handler = AgentFrameworkHandler(voice_channel=voice, sms_channel=sms, create_agent=create_agent)

# Option 1: FastAPI (local dev / self-hosted / any cloud VM)
server = TACServer(tac=tac, voice_channel=voice, sms_channel=sms, message_handler=handler)

# Option 2: Azure Foundry Agent Service
server = FoundryServer(tac=tac, voice_channel=voice, sms_channel=sms,
                       message_handler=handler, foundry_agent=from_agent_framework(my_agent))

# Option 3: AWS Bedrock AgentCore (typically with StrandsHandler, but any handler works)
server = AgentCoreServer(tac=tac, voice_channel=voice, sms_channel=sms, message_handler=handler)
```

Same channels, same handler, same `TACRoutes`. The server wrapper is the only thing that changes.

The `MessageHandler` protocol is the seam. TAC doesn't know or care which agent framework or cloud platform is behind it.

---

## Full Examples: Building an Omnichannel Agent

Five complete examples showing the same Owl Internet customer service agent built with each approach. All use the same Twilio phone number, same TAC configuration, same tools — the only difference is the agent framework and deployment target.

### Example 1: Directly with TAC + OpenAI (no agent framework SDK)

No SDK needed. TAC provides channels, routes, memory, and the callback system. You implement `on_message_ready` yourself with any LLM client.

```python
"""
Owl Internet Customer Service — TAC + OpenAI Chat Completions

No agent framework SDK. Directly uses TAC's callback system with
the OpenAI client. Deploys on TACServer (FastAPI).
"""

import os
from typing import Optional

from dotenv import load_dotenv
from openai import AsyncOpenAI

from tac import TAC, TACConfig
from tac.adapters.openai import with_tac_memory
from tac.channels.sms import SMSChannel
from tac.channels.voice import VoiceChannel
from tac.core.logging import get_logger, setup_logging
from tac.models.session import ConversationSession
from tac.models.tac import TACMemoryResponse
from tac.server import TACServer
from tac.session import ThreadSafeSessionManager
from tac.tools.memory import create_memory_tool
from tac.tools.knowledge import create_knowledge_tool

load_dotenv()
setup_logging(log_level="INFO")
logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# TAC core
# ---------------------------------------------------------------------------

tac = TAC(config=TACConfig.from_env())
voice = VoiceChannel(tac, session_manager=ThreadSafeSessionManager())
sms = SMSChannel(tac)

# ---------------------------------------------------------------------------
# OpenAI client
# ---------------------------------------------------------------------------

openai_client = AsyncOpenAI(api_key=os.environ["TWILIO_TAC_OPENAI_API_KEY"])

# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

VOICE_SYSTEM_PROMPT = (
    "You are Owl Internet's customer service assistant on a phone call. "
    "Keep responses clear, concise, and conversational. "
    "Use plain text only — no markdown, no lists, no special formatting."
)

SMS_SYSTEM_PROMPT = (
    "You are Owl Internet's customer service assistant over SMS. "
    "Keep responses concise and formatted for text messaging."
)

# ---------------------------------------------------------------------------
# Tools (plain functions — OpenAI function calling format)
# ---------------------------------------------------------------------------

tools = [
    {
        "type": "function",
        "function": {
            "name": "look_up_outage",
            "description": "Check if there is a recent internet outage in a specific zip code.",
            "parameters": {
                "type": "object",
                "properties": {"zip_code": {"type": "string"}},
                "required": ["zip_code"],
            },
        },
    },
]


async def call_tool(name: str, args: dict) -> str:
    if name == "look_up_outage":
        return f"No reported outages in {args['zip_code']}. Service is operating normally."
    return "Unknown tool."


# ---------------------------------------------------------------------------
# Conversation history (per conversation)
# ---------------------------------------------------------------------------

conversation_messages: dict[str, list[dict]] = {}

# ---------------------------------------------------------------------------
# Message handler — this is what the SDKs automate
# ---------------------------------------------------------------------------


async def handle_message_ready(
    user_message: str,
    context: ConversationSession,
    memory_response: Optional[TACMemoryResponse],
) -> None:
    conv_id = context.conversation_id
    system_prompt = VOICE_SYSTEM_PROMPT if context.channel == "voice" else SMS_SYSTEM_PROMPT

    if conv_id not in conversation_messages:
        conversation_messages[conv_id] = []

    conversation_messages[conv_id].append({"role": "user", "content": user_message})

    # with_tac_memory injects memory context and profile into the system message
    client = with_tac_memory(openai_client, memory_response, context)

    messages = [{"role": "system", "content": system_prompt}] + conversation_messages[conv_id]

    try:
        # Call OpenAI — handle tool calls in a loop
        while True:
            response = await client.chat.completions.create(
                model="gpt-4o",
                messages=messages,
                tools=tools,
            )
            choice = response.choices[0]

            if choice.finish_reason == "tool_calls":
                messages.append(choice.message.model_dump())
                for tc in choice.message.tool_calls:
                    import json
                    result = await call_tool(tc.function.name, json.loads(tc.function.arguments))
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
                continue

            # Final text response
            llm_response = choice.message.content or ""
            break

        conversation_messages[conv_id].append({"role": "assistant", "content": llm_response})

        # Send response back through the appropriate TAC channel
        if context.channel == "voice":
            await voice.send_response(conv_id, llm_response, role="assistant")
        elif context.channel == "sms":
            await sms.send_response(conv_id, llm_response, role="assistant")

    except Exception as e:
        logger.error("Error processing message", conversation_id=conv_id, error=str(e))
        error_msg = "Sorry, something went wrong. Please try again."
        if context.channel == "voice":
            await voice.send_response(conv_id, error_msg, role="assistant")
        elif context.channel == "sms":
            await sms.send_response(conv_id, error_msg, role="assistant")


# ---------------------------------------------------------------------------
# Wire callback and start server
# ---------------------------------------------------------------------------

tac.on_message_ready(handle_message_ready)

if __name__ == "__main__":
    server = TACServer(tac=tac, voice_channel=voice, sms_channel=sms)
    server.start()
```

**What you get:** Voice + SMS on a single Twilio number, memory recall, tool calling. ~100 lines of application code. No agent framework dependency.

**What you manage yourself:** Conversation history, tool call loop, channel dispatch, error handling. This is what the SDKs automate.

---

### Example 2: tac-agent-framework + Azure Foundry Agent Service

Uses Microsoft Agent Framework for the agent, `AgentFrameworkHandler` for the TAC bridge, and `FoundryServer` for Azure Foundry deployment.

```python
"""
Owl Internet Customer Service — Agent Framework + Foundry Agent Service

Uses Microsoft Agent Framework with Azure OpenAI. Deployed as a
Foundry hosted agent with TAC voice/SMS routes alongside /responses.
"""

import os

from agent_framework import Agent, ai_function
from agent_framework.azure import AzureOpenAIResponsesClient
from azure.ai.agentserver.agentframework import from_agent_framework
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv

from tac import TAC, TACConfig
from tac.channels.sms import SMSChannel
from tac.channels.voice import VoiceChannel
from tac.models.session import ConversationSession
from tac.session import ThreadSafeSessionManager
from tac_agent_framework import AgentFrameworkHandler, FoundryServer
from tac_agent_framework.tools import create_knowledge_tool, create_memory_recall_tool

load_dotenv()

# ---------------------------------------------------------------------------
# Azure AI client
# ---------------------------------------------------------------------------

credential = DefaultAzureCredential()
client = AzureOpenAIResponsesClient(
    credential=credential,
    project_endpoint=os.environ["AZURE_AI_PROJECT_ENDPOINT"],
    deployment_name="gpt-4o",
)

# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

VOICE_SYSTEM_PROMPT = (
    "You are Owl Internet's customer service assistant on a phone call. "
    "Keep responses clear, concise, and conversational. "
    "Use plain text only — no markdown, no lists, no special formatting."
)

SMS_SYSTEM_PROMPT = (
    "You are Owl Internet's customer service assistant over SMS. "
    "Keep responses concise and formatted for text messaging."
)

# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@ai_function
def look_up_outage(zip_code: str) -> str:
    """Check if there is a recent internet outage in a specific zip code."""
    return f"No reported outages in {zip_code}. Service is operating normally."


@ai_function
def get_available_plans(zip_code: str) -> str:
    """Look up available internet plans for a zip code."""
    return "Available plans: Basic ($39.99/mo, 100 Mbps), Pro ($59.99/mo, 500 Mbps)"


# ---------------------------------------------------------------------------
# TAC core
# ---------------------------------------------------------------------------

tac = TAC(config=TACConfig.from_env())
voice = VoiceChannel(tac, session_manager=ThreadSafeSessionManager())
sms = SMSChannel(tac)

knowledge_base_id = os.environ.get("TWILIO_TAC_KNOWLEDGE_BASE_ID")

# ---------------------------------------------------------------------------
# Agent factory — called once per voice call, once per SMS message
# ---------------------------------------------------------------------------


def create_agent(session: ConversationSession) -> Agent:
    prompt = VOICE_SYSTEM_PROMPT if session.channel == "voice" else SMS_SYSTEM_PROMPT

    tools = [create_memory_recall_tool(tac, session), look_up_outage, get_available_plans]
    if knowledge_base_id:
        tools.append(create_knowledge_tool(tac, knowledge_base_id=knowledge_base_id))

    return client.as_agent(name="OwlAgent", instructions=prompt, tools=tools)


# ---------------------------------------------------------------------------
# Foundry hosted agent — wraps a ChatAgent for /responses endpoint
# ---------------------------------------------------------------------------

chat_agent = client.as_agent(
    name="OwlAgent",
    instructions="You are Owl Internet's helpful customer service assistant.",
    tools=[look_up_outage, get_available_plans],
)
foundry_agent = from_agent_framework(chat_agent)

# ---------------------------------------------------------------------------
# Server — TAC routes + Foundry /responses on one Starlette app
# ---------------------------------------------------------------------------

server = FoundryServer(
    tac=tac,
    voice_channel=voice,
    sms_channel=sms,
    message_handler=AgentFrameworkHandler(
        voice_channel=voice,
        sms_channel=sms,
        create_agent=create_agent,
    ),
    foundry_agent=foundry_agent,
)

if __name__ == "__main__":
    server.start()
```

**What you get:**
- `POST /responses` — Foundry agent invocation (OpenAI Responses API)
- `GET /liveness`, `GET /readiness` — Foundry health checks
- `POST /twiml` — Twilio voice incoming calls
- `WS /ws` — Twilio voice WebSocket streaming
- `POST /webhook` — Twilio SMS webhooks
- `POST /conversation-relay-callback` — Twilio voice callbacks
- Automatic conversation persistence, OpenTelemetry tracing, OAuth consent
- Per-call voice agent caching, SMS session persistence, memory recall

**What the SDK handles for you:** Agent lifecycle (caching, cleanup), streaming bridge (`agent.run(stream=True)` → `AsyncGenerator[str]` → `voice_channel.send_response()`), SMS session load/save, channel dispatch, error handling with fallback responses.

---

### Example 3: tac-strands + AWS Bedrock AgentCore

Uses Strands Agents for the agent, `StrandsHandler` for the TAC bridge, and `AgentCoreServer` for AWS Bedrock AgentCore deployment.

```python
"""
Owl Internet Customer Service — Strands + Bedrock AgentCore

Uses Strands Agents with OpenAI model. Deployed on Bedrock AgentCore
with TAC voice/SMS routes alongside /invocations.
"""

import os

from dotenv import load_dotenv
from strands import Agent
from strands.models.openai import OpenAIModel

from tac import TAC, TACConfig
from tac.channels.sms import SMSChannel
from tac.channels.voice import VoiceChannel
from tac.core.logging import get_logger, setup_logging
from tac.models.session import ConversationSession
from tac.session import ThreadSafeSessionManager
from tac_strands import StrandsHandler, AgentCoreServer
from tac_strands.agent_proxy import AgentProxy, LocalAgentProxy
from tac_strands.tools.knowledge import create_knowledge_tool
from tac_strands.tools.memory import create_memory_recall_tool

load_dotenv()
setup_logging(log_level="INFO")
logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = (
    "You are Owl Internet's customer service assistant. "
    "You help customers with internet service issues, plan information, "
    "and outage reports. Be helpful, concise, and professional. "
    "When on a voice call, keep responses conversational and avoid markdown."
)

# ---------------------------------------------------------------------------
# Tools (Strands @tool decorator)
# ---------------------------------------------------------------------------

from strands.types.tools import tool


@tool
def look_up_outage(zip_code: str) -> str:
    """Check if there is a recent internet outage in a specific zip code."""
    return f"No reported outages in {zip_code}. Service is operating normally."


@tool
def get_available_plans(zip_code: str) -> str:
    """Look up available internet plans for a zip code."""
    return "Available plans: Basic ($39.99/mo, 100 Mbps), Pro ($59.99/mo, 500 Mbps)"


# ---------------------------------------------------------------------------
# TAC core
# ---------------------------------------------------------------------------

tac = TAC(config=TACConfig.from_env())
voice = VoiceChannel(tac, session_manager=ThreadSafeSessionManager())
sms = SMSChannel(tac)

knowledge_base_id = os.environ.get("TWILIO_TAC_KNOWLEDGE_BASE_ID")

# ---------------------------------------------------------------------------
# Agent factory — called once per voice call, once per SMS message
# ---------------------------------------------------------------------------

model = OpenAIModel(
    client_args={"api_key": os.environ["TWILIO_TAC_OPENAI_API_KEY"]},
    model_id="gpt-4o",
    params={"max_tokens": 2048, "temperature": 0.7},
)


async def create_agent_factory(tac: TAC):
    """Async factory that initializes async tools at startup, returns a sync factory."""
    base_tools = [look_up_outage, get_available_plans]

    knowledge_tool = await create_knowledge_tool(tac=tac, knowledge_base_id=knowledge_base_id)
    if knowledge_tool:
        base_tools.append(knowledge_tool)

    def factory(conversation_id: str, profile_id: str) -> AgentProxy:
        tac_session = ConversationSession(
            profile_id=profile_id,
            conversation_id=conversation_id,
            channel="voice",
            profile=None,
            author_info=None,
            ai_agent_info=None,
        )

        recall_tool = create_memory_recall_tool(tac, tac_session)
        tools = [recall_tool, *base_tools]

        agent = Agent(
            model=model,
            system_prompt=SYSTEM_PROMPT,
            tools=tools,
        )
        return LocalAgentProxy(agent)

    return factory


# ---------------------------------------------------------------------------
# Server — TAC routes + AgentCore /invocations on one Starlette app
# ---------------------------------------------------------------------------

import asyncio

agent_factory = asyncio.run(create_agent_factory(tac))

server = AgentCoreServer(
    tac=tac,
    voice_channel=voice,
    sms_channel=sms,
    message_handler=StrandsHandler(
        voice_channel=voice,
        sms_channel=sms,
        agent_factory=agent_factory,
    ),
)

if __name__ == "__main__":
    server.start()
```

**What you get:**
- `POST /invocations` — Bedrock AgentCore agent invocation
- `GET /ping` — Bedrock health check (HEALTHY/HEALTHY_BUSY)
- `POST /twiml` — Twilio voice incoming calls
- `WS /ws` — Twilio voice WebSocket streaming
- `POST /webhook` — Twilio SMS webhooks
- `POST /conversation-relay-callback` — Twilio voice callbacks
- Active task tracking (auto-busy ping while processing)
- Per-call voice agent caching, ephemeral SMS agents, memory recall

**What the SDK handles for you:** Agent lifecycle (caching, cleanup via `agent.cleanup()`), streaming bridge (`agent.stream_async()` → parse Bedrock `contentBlockDelta` events → `yield str` → `voice_channel.send_response()`), channel dispatch, error handling with fallback responses, `AgentProxy` abstraction for local/remote execution.

---

### Example 4: tac-agent-framework + TACServer (self-hosted)

Same Agent Framework handler as Example 2, but deployed on `TACServer` instead of `FoundryServer`. No Azure Foundry dependency — deploy anywhere you can run a Python process.

```python
"""
Owl Internet Customer Service — Agent Framework + TACServer

Uses Microsoft Agent Framework with Azure OpenAI. Self-hosted on
TACServer (FastAPI). No Foundry, no cloud runtime dependency.
"""

import os

from agent_framework import Agent, ai_function
from agent_framework.azure import AzureOpenAIResponsesClient
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv

from tac import TAC, TACConfig
from tac.channels.sms import SMSChannel
from tac.channels.voice import VoiceChannel
from tac.models.session import ConversationSession
from tac.server import TACServer
from tac.session import ThreadSafeSessionManager
from tac_agent_framework import AgentFrameworkHandler
from tac_agent_framework.tools import create_knowledge_tool, create_memory_recall_tool

load_dotenv()

# ---------------------------------------------------------------------------
# Azure AI client
# ---------------------------------------------------------------------------

credential = DefaultAzureCredential()
client = AzureOpenAIResponsesClient(
    credential=credential,
    project_endpoint=os.environ["AZURE_AI_PROJECT_ENDPOINT"],
    deployment_name="gpt-4o",
)

# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

VOICE_SYSTEM_PROMPT = (
    "You are Owl Internet's customer service assistant on a phone call. "
    "Keep responses clear, concise, and conversational. "
    "Use plain text only — no markdown, no lists, no special formatting."
)

SMS_SYSTEM_PROMPT = (
    "You are Owl Internet's customer service assistant over SMS. "
    "Keep responses concise and formatted for text messaging."
)

# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@ai_function
def look_up_outage(zip_code: str) -> str:
    """Check if there is a recent internet outage in a specific zip code."""
    return f"No reported outages in {zip_code}. Service is operating normally."


@ai_function
def get_available_plans(zip_code: str) -> str:
    """Look up available internet plans for a zip code."""
    return "Available plans: Basic ($39.99/mo, 100 Mbps), Pro ($59.99/mo, 500 Mbps)"


# ---------------------------------------------------------------------------
# TAC core
# ---------------------------------------------------------------------------

tac = TAC(config=TACConfig.from_env())
voice = VoiceChannel(tac, session_manager=ThreadSafeSessionManager())
sms = SMSChannel(tac)

knowledge_base_id = os.environ.get("TWILIO_TAC_KNOWLEDGE_BASE_ID")

# ---------------------------------------------------------------------------
# Agent factory — called once per voice call, once per SMS message
# ---------------------------------------------------------------------------


def create_agent(session: ConversationSession) -> Agent:
    prompt = VOICE_SYSTEM_PROMPT if session.channel == "voice" else SMS_SYSTEM_PROMPT

    tools = [create_memory_recall_tool(tac, session), look_up_outage, get_available_plans]
    if knowledge_base_id:
        tools.append(create_knowledge_tool(tac, knowledge_base_id=knowledge_base_id))

    return client.as_agent(name="OwlAgent", instructions=prompt, tools=tools)


# ---------------------------------------------------------------------------
# Server — TACServer (FastAPI), no cloud runtime
# ---------------------------------------------------------------------------

server = TACServer(
    tac=tac,
    voice_channel=voice,
    sms_channel=sms,
    message_handler=AgentFrameworkHandler(
        voice_channel=voice,
        sms_channel=sms,
        create_agent=create_agent,
    ),
)

if __name__ == "__main__":
    server.start()
```

**What you get:**
- `POST /twiml` — Twilio voice incoming calls
- `WS /ws` — Twilio voice WebSocket streaming
- `POST /webhook` — Twilio SMS webhooks
- `POST /conversation-relay-callback` — Twilio voice callbacks
- `GET /health` — basic health check
- Per-call voice agent caching, SMS session persistence, memory recall

**Compared to Example 2 (FoundryServer):** No `POST /responses`, no Foundry health checks, no auto conversation persistence, no OpenTelemetry setup. You get TAC's Twilio routes and the handler's agent lifecycle — nothing more. Deploy on a VM, container, App Service, or any host.

**The handler code is identical.** The only difference is `TACServer(...)` instead of `FoundryServer(..., foundry_agent=...)`. No Foundry agent needed since there's no `/responses` endpoint to serve.

---

### Example 5: tac-strands + TACServer (self-hosted)

Same Strands handler as Example 3, but deployed on `TACServer` instead of `AgentCoreServer`. No Bedrock AgentCore dependency — deploy anywhere.

```python
"""
Owl Internet Customer Service — Strands + TACServer

Uses Strands Agents with OpenAI model. Self-hosted on
TACServer (FastAPI). No AgentCore, no cloud runtime dependency.
"""

import asyncio
import os

from dotenv import load_dotenv
from strands import Agent
from strands.models.openai import OpenAIModel
from strands.types.tools import tool

from tac import TAC, TACConfig
from tac.channels.sms import SMSChannel
from tac.channels.voice import VoiceChannel
from tac.core.logging import get_logger, setup_logging
from tac.models.session import ConversationSession
from tac.server import TACServer
from tac.session import ThreadSafeSessionManager
from tac_strands import StrandsHandler
from tac_strands.agent_proxy import AgentProxy, LocalAgentProxy
from tac_strands.tools.knowledge import create_knowledge_tool
from tac_strands.tools.memory import create_memory_recall_tool

load_dotenv()
setup_logging(log_level="INFO")
logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = (
    "You are Owl Internet's customer service assistant. "
    "You help customers with internet service issues, plan information, "
    "and outage reports. Be helpful, concise, and professional. "
    "When on a voice call, keep responses conversational and avoid markdown."
)

# ---------------------------------------------------------------------------
# Tools (Strands @tool decorator)
# ---------------------------------------------------------------------------


@tool
def look_up_outage(zip_code: str) -> str:
    """Check if there is a recent internet outage in a specific zip code."""
    return f"No reported outages in {zip_code}. Service is operating normally."


@tool
def get_available_plans(zip_code: str) -> str:
    """Look up available internet plans for a zip code."""
    return "Available plans: Basic ($39.99/mo, 100 Mbps), Pro ($59.99/mo, 500 Mbps)"


# ---------------------------------------------------------------------------
# TAC core
# ---------------------------------------------------------------------------

tac = TAC(config=TACConfig.from_env())
voice = VoiceChannel(tac, session_manager=ThreadSafeSessionManager())
sms = SMSChannel(tac)

knowledge_base_id = os.environ.get("TWILIO_TAC_KNOWLEDGE_BASE_ID")

# ---------------------------------------------------------------------------
# Agent factory — called once per voice call, once per SMS message
# ---------------------------------------------------------------------------

model = OpenAIModel(
    client_args={"api_key": os.environ["TWILIO_TAC_OPENAI_API_KEY"]},
    model_id="gpt-4o",
    params={"max_tokens": 2048, "temperature": 0.7},
)


async def create_agent_factory(tac: TAC):
    """Async factory that initializes async tools at startup, returns a sync factory."""
    base_tools = [look_up_outage, get_available_plans]

    knowledge_tool = await create_knowledge_tool(tac=tac, knowledge_base_id=knowledge_base_id)
    if knowledge_tool:
        base_tools.append(knowledge_tool)

    def factory(conversation_id: str, profile_id: str) -> AgentProxy:
        tac_session = ConversationSession(
            profile_id=profile_id,
            conversation_id=conversation_id,
            channel="voice",
            profile=None,
            author_info=None,
            ai_agent_info=None,
        )

        recall_tool = create_memory_recall_tool(tac, tac_session)
        tools = [recall_tool, *base_tools]

        agent = Agent(
            model=model,
            system_prompt=SYSTEM_PROMPT,
            tools=tools,
        )
        return LocalAgentProxy(agent)

    return factory


# ---------------------------------------------------------------------------
# Server — TACServer (FastAPI), no cloud runtime
# ---------------------------------------------------------------------------

agent_factory = asyncio.run(create_agent_factory(tac))

server = TACServer(
    tac=tac,
    voice_channel=voice,
    sms_channel=sms,
    message_handler=StrandsHandler(
        voice_channel=voice,
        sms_channel=sms,
        agent_factory=agent_factory,
    ),
)

if __name__ == "__main__":
    server.start()
```

**What you get:**
- `POST /twiml` — Twilio voice incoming calls
- `WS /ws` — Twilio voice WebSocket streaming
- `POST /webhook` — Twilio SMS webhooks
- `POST /conversation-relay-callback` — Twilio voice callbacks
- `GET /health` — basic health check
- Per-call voice agent caching, ephemeral SMS agents, memory recall

**Compared to Example 3 (AgentCoreServer):** No `POST /invocations`, no `/ping` with HEALTHY/HEALTHY_BUSY, no task tracking. You get TAC's Twilio routes and the handler's agent lifecycle — nothing more.

**The handler code is identical.** The only difference is `TACServer(...)` instead of `AgentCoreServer(...)`. No `bedrock-agentcore` in your dependency tree.

---

### Side-by-side comparison

| | Ex 1: TAC + OpenAI | Ex 2: Agent Fwk + Foundry | Ex 3: Strands + AgentCore | Ex 4: Agent Fwk + TACServer | Ex 5: Strands + TACServer |
|---|---|---|---|---|---|
| Agent framework | None (raw OpenAI) | Agent Framework | Strands Agents | Agent Framework | Strands Agents |
| Server | `TACServer` | `FoundryServer` | `AgentCoreServer` | `TACServer` | `TACServer` |
| Cloud dependency | None | `azure-ai-agentserver-core` | `bedrock-agentcore` | None | None |
| Handler | Manual callback | `AgentFrameworkHandler` | `StrandsHandler` | `AgentFrameworkHandler` | `StrandsHandler` |
| Voice agent lifecycle | Manual | Handler (auto) | Handler (auto) | Handler (auto) | Handler (auto) |
| SMS agent lifecycle | Manual | Handler (auto) | Handler (auto) | Handler (auto) | Handler (auto) |
| Channel dispatch | Manual `if/elif` | Handler (auto) | Handler (auto) | Handler (auto) | Handler (auto) |
| Cloud endpoints | None | `/responses`, `/liveness` | `/invocations`, `/ping` | None | None |
| Twilio endpoints | All | All | All | All | All |
| Deploy to | Anywhere | Azure Foundry | AWS AgentCore | Anywhere | Anywhere |

**Key takeaway:** Examples 4 and 5 are identical to Examples 2 and 3 except for the server line. The handler — the part that bridges the agent framework with TAC — doesn't change. The server is just where you mount it.

---

## Handler Implementations

### `AgentFrameworkHandler` (~150 lines)

```python
# tac_agent_framework/handler.py

class AgentFrameworkHandler:
    """Implements MessageHandler for Microsoft Agent Framework."""

    def __init__(
        self,
        voice_channel: VoiceChannel | None = None,
        sms_channel: SMSChannel | None = None,
        create_agent: Callable[[ConversationSession], Agent] | None = None,
        session_store: AgentSessionStore | None = None,
        on_message: Callable[[str, ConversationSession, TACMemoryResponse | None], str] | None = None,
    ):
        self.voice_channel = voice_channel
        self.sms_channel = sms_channel
        self.create_agent = create_agent
        self.on_message = on_message
        self.session_store: AgentSessionStore = session_store or InMemoryAgentSessionStore()
        self._voice_agents: dict[str, Agent] = {}
        self._voice_sessions: dict[str, AgentSession] = {}

    # -- MessageHandler protocol --

    async def handle_message(self, user_message, context, memory):
        if context.channel == "voice":
            await self._handle_voice(user_message, context)
        elif context.channel == "sms":
            await self._handle_sms(user_message, context, memory)

    async def handle_conversation_ended(self, context):
        self._cleanup_voice_agent(context.conversation_id)

    # -- Voice --

    async def _handle_voice(self, user_message, context):
        if self.voice_channel is None:
            return
        await self.voice_channel.send_response(
            context.conversation_id,
            self._stream_response(user_message, context.conversation_id),
        )

    async def _stream_response(self, prompt, conversation_id):
        agent = self._get_or_create_voice_agent(conversation_id)
        af_session = self._get_or_create_voice_session(conversation_id)
        try:
            async for chunk in agent.run(prompt, stream=True, session=af_session):
                if hasattr(chunk, "text") and chunk.text:
                    yield chunk.text
            self._background_save_session(conversation_id, af_session)
        except GeneratorExit:
            self._cleanup_voice_agent(conversation_id)
            raise

    def _get_or_create_voice_agent(self, conversation_id):
        if conversation_id not in self._voice_agents:
            session = self.voice_channel.get_conversation(conversation_id)
            self._voice_agents[conversation_id] = self.create_agent(session)
        return self._voice_agents[conversation_id]

    # ... _get_or_create_voice_session, _cleanup_voice_agent,
    #     _background_save_session follow same pattern as current code ...

    # -- SMS --

    async def _handle_sms(self, user_message, context, memory):
        if self.sms_channel is None:
            return
        if self.on_message is not None:
            augmented = self.on_message(user_message, context, memory)
        else:
            augmented = format_memory_context(memory, user_message)

        agent = self.create_agent(context)
        af_session = await self.session_store.load(context.conversation_id)
        if af_session is None:
            af_session = AgentSession(session_id=context.conversation_id)

        try:
            result = await agent.run(augmented, session=af_session)
            await self.sms_channel.send_response(
                context.conversation_id, result.text, role="assistant"
            )
        except Exception:
            await self.sms_channel.send_response(
                context.conversation_id, "Sorry, something went wrong.", role="assistant"
            )
        finally:
            await self.session_store.save(context.conversation_id, af_session)
```

### `StrandsHandler` (~120 lines)

```python
# tac_strands/handler.py

class StrandsHandler:
    """Implements MessageHandler for Strands agents."""

    def __init__(
        self,
        voice_channel: VoiceChannel | None = None,
        sms_channel: SMSChannel | None = None,
        agent_factory: Callable[[str, str], AgentProxy] | None = None,
    ):
        self.voice_channel = voice_channel
        self.sms_channel = sms_channel
        self.agent_factory = agent_factory
        self._voice_agents: dict[str, AgentProxy] = {}

    # -- MessageHandler protocol --

    async def handle_message(self, user_message, context, memory):
        if context.channel == "voice":
            await self._handle_voice(user_message, context)
        elif context.channel == "sms":
            await self._handle_sms(user_message, context)

    async def handle_conversation_ended(self, context):
        self._cleanup_voice_agent(context.conversation_id)

    # -- Voice --

    async def _handle_voice(self, user_message, context):
        if self.voice_channel is None:
            return
        await self.voice_channel.send_response(
            context.conversation_id,
            self._stream_response(user_message, context.conversation_id),
        )

    async def _stream_response(self, prompt, conversation_id):
        agent = self._get_or_create_voice_agent(conversation_id)
        try:
            async for event in agent.stream_async(prompt):
                if "event" in event and "contentBlockDelta" in event["event"]:
                    text = event["event"]["contentBlockDelta"]["delta"].get("text")
                    if text:
                        yield text
        except GeneratorExit:
            self._cleanup_voice_agent(conversation_id)
            raise

    def _get_or_create_voice_agent(self, conversation_id):
        if conversation_id not in self._voice_agents:
            session = self.voice_channel.get_conversation(conversation_id)
            profile_id = session.profile_id if session else None
            self._voice_agents[conversation_id] = self.agent_factory(
                conversation_id, profile_id
            )
        return self._voice_agents[conversation_id]

    def _cleanup_voice_agent(self, conversation_id):
        agent = self._voice_agents.pop(conversation_id, None)
        if agent:
            agent.cleanup()

    # -- SMS --

    async def _handle_sms(self, user_message, context):
        if self.sms_channel is None:
            return
        agent = self.agent_factory(context.conversation_id, context.profile_id)
        try:
            response = await agent.run_async(user_message)
            response_text = ""
            if isinstance(response, dict) and "content" in response:
                for block in response["content"]:
                    if block.get("type") == "text":
                        response_text += block.get("text", "")
            if not response_text:
                response_text = "I couldn't generate a response. Please try again."
            await self.sms_channel.send_response(
                context.conversation_id, response_text, role="assistant"
            )
        except Exception:
            await self.sms_channel.send_response(
                context.conversation_id, "Sorry, something went wrong.", role="assistant"
            )
        finally:
            agent.cleanup()
```

---

## Dependency Changes

### tac-azure `pyproject.toml` (after)

```toml
[project]
name = "tac-agent-framework"
dependencies = [
    "agent-framework",
    "tac",
]

[project.optional-dependencies]
azure = ["agent-framework-azure-ai", "azure-identity"]
foundry = ["azure-ai-agentserver-core>=1.0.0b16", "azure-ai-agentserver-agentframework>=1.0.0b16"]
dev = ["ruff", "mypy", "pytest", "pytest-asyncio"]
```

No more fastapi, uvicorn, websockets, pydantic, truststore, python-dotenv. The SDK doesn't host a server or define models. `FoundryServer` requires `pip install tac-agent-framework[foundry]`. Users deploying with FastAPI don't pull in the Foundry adapter packages.

### strands `pyproject.toml` (after)

```toml
[project]
name = "tac-strands"
dependencies = [
    "strands-agents>=1.22.0",
    "tac",
]

[project.optional-dependencies]
agentcore = ["bedrock-agentcore>=1.2.0"]
dev = ["ruff", "mypy", "pytest", "pytest-asyncio"]
```

`AgentCoreServer` requires `pip install tac-strands[agentcore]`. Users deploying with FastAPI don't pull in `bedrock-agentcore` or `boto3`.

---

## Migration Path

### For existing tac-azure users (FastAPI)

```python
# Before
from tac_azure import OmniChannelServer
server = OmniChannelServer(tac=tac, create_agent=create_agent, public_domain="...", ...)
server.serve()

# After
from tac.channels.voice import VoiceChannel
from tac.channels.sms import SMSChannel
from tac.server import TACServer
from tac.session import ThreadSafeSessionManager
from tac_agent_framework import AgentFrameworkHandler

voice = VoiceChannel(tac, session_manager=ThreadSafeSessionManager())
sms = SMSChannel(tac)
server = TACServer(
    tac=tac, voice_channel=voice, sms_channel=sms,
    message_handler=AgentFrameworkHandler(
        voice_channel=voice, sms_channel=sms, create_agent=create_agent,
    ),
)
server.start()
```

### For tac-azure users deploying to Foundry Agent Service

```python
# After (Foundry deployment)
from azure.ai.agentserver.agentframework import from_agent_framework
from tac.channels.voice import VoiceChannel
from tac.channels.sms import SMSChannel
from tac.session import ThreadSafeSessionManager
from tac_agent_framework import AgentFrameworkHandler, FoundryServer

voice = VoiceChannel(tac, session_manager=ThreadSafeSessionManager())
sms = SMSChannel(tac)
server = FoundryServer(
    tac=tac, voice_channel=voice, sms_channel=sms,
    message_handler=AgentFrameworkHandler(
        voice_channel=voice, sms_channel=sms, create_agent=create_agent,
    ),
    foundry_agent=from_agent_framework(my_agent),
)
server.start()
```

### For existing strands users

```python
# Before
from strands_communications.twilio import OmniChannelServer
server = OmniChannelServer(agent_factory=factory, tac=tac, tac_config=config)
tac.on_message_ready(server.handle_message_ready)
server.serve()

# After (Bedrock AgentCore deployment)
from tac.channels.voice import VoiceChannel
from tac.channels.sms import SMSChannel
from tac.session import ThreadSafeSessionManager
from tac_strands import StrandsHandler, AgentCoreServer

voice = VoiceChannel(tac, session_manager=ThreadSafeSessionManager())
sms = SMSChannel(tac)
server = AgentCoreServer(
    tac=tac, voice_channel=voice, sms_channel=sms,
    message_handler=StrandsHandler(
        voice_channel=voice, sms_channel=sms, agent_factory=factory,
    ),
)
server.start()
```

### Strands migration notes

The Strands SDK must also address:
- **`stream_generator` removal:** Migrate from passing `stream_generator` to `ThreadSafeSessionManager` (old pattern) to using `on_message_ready` callback + `voice_channel.send_response()` (new pattern). This is already forced by TAC HEAD.
- **Import path change:** `tac.channels.session_manager` → `tac.session`
- **SMS webhook format:** The fabricated Conversations API webhook format needs resolution (see Open Questions).

---

## Full Architecture Diagram

```
                    ┌──────────────┐
                    │   TACServer  │  FastAPI — local dev, self-hosted
                    │  (for either │  No cloud platform dependency
                    │   SDK)       │
                    └──────┬───────┘
                           │
         ┌─────────────────┼─────────────────┐
         │                 │                  │
   ┌─────┴──────┐   ┌─────┴──────┐   ┌──────┴───────┐
   │ tac-strands │   │    TAC     │   │ tac-agent-fw │
   │             │   │            │   │              │
   │ Strands     │   │ Channels   │   │ Agent Fwk    │
   │ Handler     │   │ Routes     │   │ Handler      │
   │             │   │ Tools      │   │              │
   │ AgentCore   │   │ Protocols  │   │ Foundry      │
   │ Server      │   │ Sessions   │   │ Server       │
   └─────────────┘   └────────────┘   └──────────────┘
        AWS                                Azure
```

---

## Open Questions

1. **Naming:** `tac-agent-framework` vs `tac-microsoft-agent-framework`. For Strands: `tac-strands` vs `strands-tac`. Should follow whichever convention TAC establishes.

2. **Should tool helpers exist at all?** The memory tool bridge is `tac_tool.implementation`. These could be documentation. Counter-argument: keeping them in the SDK absorbs TAC tool API changes so user code doesn't break on TAC upgrades.

3. **Strands `AgentProxy` — should it move to Strands itself?** The `LocalAgentProxy` / `RemoteAgentProxy` abstraction is about Strands + Bedrock AgentCore, not Twilio. It might belong upstream.

4. **Strands SMS webhook format:** The current Strands SDK fabricates Twilio Conversations API events from raw SMS webhooks. Options: (a) TAC's `SMSChannel` adds raw SMS support, (b) the adapter keeps the translation layer, (c) Strands examples use Twilio Conversations webhooks directly.

5. **Should `format_memory_context()` stay in tac-azure?** It composes `TACMemoryResponse` data into an augmented prompt string. TAC provides `build_memory_prompts()` which returns a list of sections. The adapter's function is a thin composition layer — reasonable to keep as a convenience.

6. **PR #10 (`simplify-examples-and-add-omni-server`):** This open PR on strands-communications-twilio goes in a similar direction — deletes `AgentFrameworkConnector`, `OmniChannelServer`, and `AgentProxy`, replacing them with `OmniServer` backed by `BedrockAgentCoreApp`. The example simplification is good. However, it pushes agent lifecycle (caching, streaming, channel routing) entirely to userland and creates channels internally. The `OmniServer` should be reworked to accept channels and a `MessageHandler`, becoming `AgentCoreServer` as described here.

7. **Foundry `from_agent_framework()` vs `create_agent` factory:** The `FoundryServer` takes a `foundry_agent` (for `/responses`) and a `message_handler` with a `create_agent` factory (for Twilio voice/SMS). These create separate agent instances — one for Foundry invocations, one per Twilio conversation. This is correct (they serve different interaction patterns), but the developer needs to understand why they provide the agent twice. Documentation should make this clear.

8. **Foundry conversation persistence vs TAC conversations:** Foundry's `FoundryCBAgent` auto-persists conversations to Foundry's conversation store. TAC uses Maestro for conversation management. These are separate systems. When an agent handles both Foundry `/responses` calls and Twilio voice/SMS, conversation history lives in two places. Whether to unify or keep separate is an open question.
