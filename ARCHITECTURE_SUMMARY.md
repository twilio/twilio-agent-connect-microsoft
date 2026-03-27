# TAC + Partner SDK Architecture

## Three Goals

| # | Goal | Problem today |
|---|---|---|
| **1** | **Clear ownership** between TAC and partner SDKs | Both partner SDKs copy ~400 lines of Twilio-specific code from TAC, then diverge. Bugs get fixed in one place but not the other. |
| **2** | **Unified developer interface** across all partner SDKs (MS Agent Framework, Strands, future partners) | The two SDKs have different factory signatures and different class structures. Adding a new partner means designing the interface from scratch each time. |
| **3** | **Composable deployment** — choose agent framework and deployment target independently | Each SDK hardcodes its own web server. But not every partner has a cloud runtime (OpenAI has no hosted runtime — their SDK just wraps the Agents SDK), and runtimes that do exist may not be compatible yet (Foundry hosted agents may not support TAC by Signal conference). Developers need to use `TACServer` or their own infra today and optionally adopt a cloud runtime later — without rewriting. |

---

## Solution: Three Composable Interfaces

Every partner SDK exports three classes with the same names and the same shape.

```
┌─────────────────────────────────────────────────────────────────────┐
│                        DEVELOPER CODE                               │
│            create_agent factory, system prompts, tools               │
└────────────────────────────┬────────────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────────────┐
│                                                                     │
│  Cloud runtime path: OmniChannelServer              PARTNER SDK     │
│  ┌─────────────────────────────┐ ┌─────────────────────────────┐   │
│  │ AgentFrameworkBridge          │ │ RuntimeServer               │   │
│  │                             │ │                             │   │
│  │ Takes a create_agent        │ │ Integrates TACRoutes into   │   │
│  │ factory. When TAC channels  │ │ a cloud runtime app         │   │
│  │ fire callbacks, creates/    │ │ (Foundry, AgentCore)        │   │
│  │ retrieves an agent and      │ │                             │   │
│  │ runs it.                    │ │                             │   │
│  └──────────────┬──────────────┘ └──────────────┬──────────────┘   │
│                 │                                │                   │
│─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ── OR ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─│
│                 │                                │                   │
│  Self-hosted path: AgentFrameworkBridge + TACServer                   │
│  ┌─────────────────────────────┐ ┌─────────────────────────────┐   │
│  │ AgentFrameworkBridge          │ │ TACServer           (TAC)   │   │
│  │                             │ │                             │   │
│  │ (same as above)             │ │ Integrates TACRoutes into   │   │
│  │                             │ │ a plain FastAPI app for     │   │
│  │                             │ │ self-hosted deployment      │   │
│  └──────────────┬──────────────┘ └──────────────┬──────────────┘   │
└────────────────┼────────────────────────────────┼───────────────────┘
                 │ creates                        │ creates
┌────────────────▼────────────────────────────────▼───────────────────┐
│                              TAC                                    │
│                                                                     │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────────────────┐ │
│  │ VoiceChannel │  │ SMSChannel   │  │ TACRoutes                  │ │
│  │              │  │              │  │                            │ │
│  │ Twilio voice │  │ Twilio SMS   │  │ HTTP adapter — parses      │ │
│  │ protocol     │  │ protocol     │  │ requests, validates        │ │
│  │ (WebSocket,  │  │ (webhooks,   │  │ webhooks, calls channel    │ │
│  │ TwiML,       │  │ Twilio SMS   │  │ methods                    │ │
│  │ streaming)   │  │ API)         │  │                            │ │
│  └──────┬───────┘  └──────┬───────┘  └────────────────────────────┘ │
│         │                 │                                         │
│  ┌──────▼─────────────────▼───────────────────────────────────────┐ │
│  │ TAC Core                                                       │ │
│  │ Callbacks (on_message_ready, on_conversation_ended, on_interrupt│)│
│  │ Memory retrieval, profile lookup, config, models, tools        │ │
│  └────────────────────────┬───────────────────────────────────────┘ │
└───────────────────────────┼─────────────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────────────┐
│                         TWILIO                                      │
│              Voice calls, SMS, Conversations API                    │
└─────────────────────────────────────────────────────────────────────┘
```

Starting from the top — here's what `OmniChannelServer` creates:

```
OmniChannelServer
│
│   On construction, creates two things:
│
├── 1. AgentFrameworkBridge (PARTNER SDK)
│       Creates TAC channels and wires the SDK's framework-specific agent
│       logic to them (e.g., MS Agent Framework streaming, Strands streaming).
│       No HTTP. No server. Just "when a message arrives, run the agent."
│       │
│       ├── creates VoiceChannel (TAC)
│       ├── creates SMSChannel (TAC)
│       └── wires callbacks:
│             tac.on_message_ready      → run agent, stream/send response
│             tac.on_conversation_ended → clean up agent
│             tac.on_interrupt          → cancel in-flight stream
│
├── 2. RuntimeServer (PARTNER SDK)
│       Integrates TACRoutes into the partner's cloud runtime.
│       No agent logic. Just "mount these route handlers on my app and run it."
│       │
│       ├── creates TACRoutes (TAC) from the handler's channels
│       │     TACRoutes has the route handlers (handle_twiml, handle_websocket, etc.)
│       │     They're framework-agnostic — just async functions that take a Request
│       │
│       ├── mounts those handlers onto the cloud runtime's app:
│       │     Foundry RuntimeServer   → foundry_app.routes.extend(...)
│       │     AgentCore RuntimeServer → agentcore_app.add_route(...)
│       │
│       └── .start() runs the server
│
│   On .start(), starts the RuntimeServer.
```

**`TACServer` is the alternative to `RuntimeServer`** — not part of `OmniChannelServer`. Developers use it when they want to deploy on their own infra (container, VM) instead of a cloud runtime. It does the same job (creates `TACRoutes`, mounts them) but onto a plain FastAPI app:

```
# No OmniChannelServer — developer wires it manually
handler = AgentFrameworkBridge(tac=tac, create_agent=factory)
server = TACServer(tac=tac, voice_channel=handler.voice_channel,
                   sms_channel=handler.sms_channel)
server.start()   # TACServer creates TACRoutes internally, mounts on FastAPI
```

**Key point:** `TACRoutes` and `AgentFrameworkBridge` never call each other. They're both plugged into TAC's channels — one from the HTTP side, one from the agent side. The channels and TAC's callback system connect them.

### What TAC provides (the building blocks)

| TAC component | What it does | Used by |
|---|---|---|
| **VoiceChannel** | Speaks Twilio's voice protocol. Handles incoming calls, manages WebSocket connections, processes ConversationRelay messages (utterances, interrupts), streams audio responses back. Fires TAC callbacks when things happen. | Created by `AgentFrameworkBridge` |
| **SMSChannel** | Speaks Twilio's SMS protocol. Processes Maestro webhooks (participant added, message created, conversation closed), sends SMS responses via Twilio API. Fires TAC callbacks when things happen. | Created by `AgentFrameworkBridge` |
| **TACRoutes** | HTTP adapter layer. Parses incoming HTTP requests (form data, JSON, WebSocket upgrades), validates Twilio webhook signatures, and calls the appropriate channel method. Framework-agnostic — just async functions that take a Starlette `Request` and return a `Response`. | Created by `RuntimeServer` or `TACServer` |
| **TACServer** | A ready-made FastAPI app. Creates `TACRoutes` from channels, mounts them on FastAPI, runs uvicorn. The self-hosted deployment option — alternative to `RuntimeServer`. | Used directly by developers who don't need a cloud runtime |
| **TAC core** | Callback system (`on_message_ready`, `on_conversation_ended`, `on_interrupt`), memory retrieval, profile lookup, config, models. The glue between channels and whatever agent logic is wired up. | Used by everything |

### Summary of interfaces

| Interface | What it does | Who uses it |
|---|---|---|
| **AgentFrameworkBridge** | Creates channels, wires SDK-specific agent logic to TAC callbacks. No HTTP, no server. | Developers who want full control over hosting |
| **RuntimeServer** | Creates `TACRoutes` from handler's channels, mounts on a cloud runtime | Developers deploying to Foundry / AgentCore |
| **OmniChannelServer** | Creates both of the above. Single `start()` call. | Developers who want the simplest path |

---

## How This Addresses Each Goal

### Goal 1 — Clear ownership

**Rule: TAC owns everything Twilio-specific. Partner SDKs own the agent framework bridge.**

| TAC provides | Partner SDK provides |
|---|---|
| Voice & SMS channels | Agent creation & caching |
| HTTP/WebSocket route handlers | Streaming bridge (framework-specific protocol) |
| Twilio webhook validation | SMS message processing (framework-specific session management) |
| Tool logic (memory, knowledge, handoff) | Tool format conversion (TAC format → framework-native format) |
| Config, models, session management | Cleanup & error handling (framework-specific lifecycle) |

Today, partner SDKs duplicate the left column. After: they only implement the right column, and get the left column from TAC.

**`TACRoutes` — the key new piece in TAC.** Route handlers (TwiML generation, WebSocket accept, SMS webhook, ConversationRelay callback) currently live inside `TACServer`'s FastAPI app and can't be reused. We extract them into a standalone `TACRoutes` class that uses framework-agnostic Starlette types (`Request`, `WebSocket`, `Response`). Any ASGI framework — FastAPI, Foundry's app, AgentCore's app, or a custom Starlette app — can mount these routes directly. `TACRoutes` is a server-layer concern — it's created by `RuntimeServer`, `TACServer`, or the developer from the handler's channels, not by the handler itself. `TACServer` is refactored to use `TACRoutes` internally (no breaking changes).

### Goal 2 — Unified developer interface

```python
# MS Agent Framework
from tac_ms_agent_framework import AgentFrameworkBridge, RuntimeServer, OmniChannelServer

# Strands
from tac_strands import AgentFrameworkBridge, RuntimeServer, OmniChannelServer

# Future partner (e.g., OpenAI)
from tac_openai import AgentFrameworkBridge, RuntimeServer, OmniChannelServer
```

Same class names. Same constructor parameters (with framework-specific extras). Same `create_agent` factory signature. A developer who learns one SDK can use any of them.

**The `create_agent` factory** — the developer's main touchpoint. The handler calls it to create an agent per conversation:

```python
def create_agent(session: ConversationSession) -> AgentType:
    # session has: conversation_id, profile_id, channel ("voice"/"sms"), profile traits, metadata
    # Returns a framework-native agent — Agent (MS AF), AgentProxy (Strands), Agent (OpenAI)
    prompt = VOICE_PROMPT if session.channel == "voice" else SMS_PROMPT
    return my_framework.create_agent(instructions=prompt, tools=[...])
```

Called once per voice call (agent persists for the call), once per SMS message (ephemeral). Unifies the current inconsistency — Azure already takes `ConversationSession`, but Strands takes raw `(conversation_id, profile_id)` and loses access to channel, profile, and metadata.

**What a new partner SDK needs to implement:**

| What | Why it's framework-specific | Size |
|---|---|---|
| Streaming bridge | Each framework streams responses differently | ~150 lines |
| SMS execution | Each framework manages conversation history differently | ~80 lines |
| Cloud runtime mount | Each cloud runtime has a different app interface | ~30 lines |
| Tool format conversion | Each framework expects tools in a different format | ~10 lines |

Everything else (channels, routes, webhook handling, tool logic, config) comes from TAC for free.

### Goal 3 — Composable deployment

Not every partner has a cloud runtime. OpenAI has no hosted agent runtime — their partner SDK would just wrap the Agents SDK and deploy via `TACServer`. Foundry hosted agents may not support TAC in time for Signal conference, so MS Agent Framework developers need `TACServer` today with an upgrade path to `RuntimeServer` later. The architecture must not couple "which agent framework" to "where it runs."

The handler has no opinion about where it runs. Developers build the handler once, then choose a deployment target:

| Deploy on... | What to combine |
|---|---|
| **Azure Foundry** | Handler + `RuntimeServer(foundry_agent=...)` |
| **AWS AgentCore** | Handler + `RuntimeServer(...)` |
| **Container / VM / any infra** | Handler + TAC's built-in server (`TACServer`) |
| **Your own web framework** | Handler → mount `handler.routes` on any ASGI app |

```python
# Step 1: Build the handler (same regardless of deployment)
handler = AgentFrameworkBridge(tac=tac, create_agent=my_agent_factory)

# Step 2: Pick a deployment target — each creates TACRoutes from handler's channels internally
server = RuntimeServer(omnichannel=handler, foundry_agent=...)   # Azure Foundry
server = RuntimeServer(omnichannel=handler)                       # AWS AgentCore
server = TACServer(tac=tac, voice_channel=handler.voice_channel,  # Container/VM
                   sms_channel=handler.sms_channel)
server.start()
```

---

## What Changes

| Where | Change | Impact |
|---|---|---|
| **TAC** | Extract reusable route handlers from the existing server into a standalone class. Add one public getter method. | Additive. No breaking changes. Minor version bump. |
| **Each partner SDK** | Delete duplicated Twilio code. Restructure around the three interfaces. Rename package. | Breaking, but both are pre-1.0 with no external consumers. |

---

## Risk

| Level | Item |
|---|---|
| **Low** | TAC changes are additive — existing `TACServer` API is unchanged. |
| **Medium** | Strands SDK uses a TAC integration pattern that changed in recent TAC versions. Migration requires updating the voice streaming wiring. |
| **Mitigated** | Both SDKs are pre-1.0, internal-only. No external consumers to break. |
