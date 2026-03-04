## Introduction

Twilio communications tools and a native Omnichannel handler for Microsoft Agent Framework, supporting ConversationRelay voice streaming and SMS. It enables you to:

- Build and deploy Twilio-powered voice and messaging applications using Azure AI agents
- Integrate communication patterns using Twilio's platform with Microsoft Agent Framework workflows

It makes it easy to manage calls, send and receive messages, and leverage Azure AI agents for advanced conversational experiences.

**Unlock the full potential of conversational AI and communications with a seamless integration between Microsoft Agent Framework and Twilio.**

**Key Benefits:**

- **True Native Integration:** Directly connects Microsoft Agent Framework with Twilio's global communications infrastructure—no glue code, no brittle adapters.
- **Omnichannel by Design:** Voice and SMS are first-class citizens, enabling unified customer journeys across channels.
- **Multi-Provider Support:** Works with Azure AI Foundry Agent Service, Azure OpenAI Responses API, or any custom LLM implementation.
- **Real-Time Intelligence:** Agents can access, update, and reason over customer memory, knowledge, and context in real time.
- **Rapid Innovation:** Unlocks new use cases—AI-powered contact centers, automated workflows, and personalized experiences—without custom backend plumbing.
- **Developer Velocity:** Both batteries-included (`OmniChannelServer`) and low-level (`OmniChannelHandler`) APIs for full control.
- **Future-Proof:** Designed to evolve with both Azure and Twilio, supporting new channels, features, and AI capabilities as they launch.

## Installation

1. **Install uv** (if not already installed):
   ```sh
   pip install uv
   ```

2. **Create and activate a virtual environment:**
   ```sh
   uv venv
   source .venv/bin/activate  # On macOS/Linux
   # .venv\Scripts\activate   # On Windows
   ```

3. **Install project dependencies:**
   ```sh
   uv pip install .
   ```

## Twilio Agent Connect (TAC) Dependency

This project depends on `twilio-agent-connect-python` (TAC), an internal Twilio library hosted in a private repository.

**TAC Repository:** https://github.com/twilio-internal/twilio-agent-connect-python

Refer to the TAC repository for setup instructions and configuration details.

### Authentication Requirements
To install this package, you need:
- GitHub authentication configured (SSH keys or personal access token)
- Access to the `twilio-internal` GitHub organization

## Examples

See the **[examples directory](examples/)** for complete working examples.

### Quick Start

**[Foundry Voice + SMS Demo](examples/foundry_voice_sms_demo/)** - **Recommended starting point**
- Multi-channel server (Voice + SMS) using Azure AI Foundry Agent Service
- Dynamic knowledge base tool creation
- Memory tool for customer context recall
- Channel-specific system prompts
- Flex escalation for human handoff

```bash
# Run the demo
uv run python examples/foundry_voice_sms_demo/server.py
```

### Additional Examples

**[Responses Voice + SMS Demo](examples/responses_voice_sms_demo/)**
- Uses Azure OpenAI Responses API (Chat Completions)
- Simpler setup without Foundry dependencies
- Same omnichannel architecture

**[Custom FastAPI Demo](examples/responses_custom_fastapi_demo/)**
- Uses `OmniChannelHandler` directly instead of `OmniChannelServer`
- Full control over FastAPI app, routing, and lifecycle
- Custom landing page example

**[File-Based SMS Sessions](examples/sms_file_sessions/)**
- Custom `SessionStore` implementation using JSON files
- SMS-only setup with session persistence across restarts
- Demonstrates `on_conversation_ended` lifecycle hook

## Configuration

Typical environment variables:

| Variable | Description |
|---|---|
| `AZURE_AI_PROJECT_ENDPOINT` | Azure AI Foundry endpoint |
| `AZURE_AI_MODEL_DEPLOYMENT_NAME` | Model deployment name (default: `gpt-4o`) |
| `TWILIO_TAC_VOICE_PUBLIC_DOMAIN` | Public domain for voice callbacks/WebSocket |
| `TWILIO_TAC_KNOWLEDGE_BASE_ID` | Knowledge base ID for tool creation (optional) |
| `TWILIO_AUTH_TOKEN` | For webhook signature validation |

See individual examples for complete environment variable requirements.

## Architecture

### Core Components

- **`OmniChannelHandler`** — Main orchestrator handling both voice and SMS channels. Manages conversation sessions, agent lifecycle, and streaming responses through TAC channels.
- **`OmniChannelServer`** — Batteries-included FastAPI wrapper with pre-wired routes for TwiML, WebSocket, SMS webhooks, and health checks.
- **`AgentLike`** / **`SessionStore`** — Protocols enabling pluggable agent implementations and session persistence backends.

### Built-in Tools

- **Memory Recall** — Query TAC's Memora client for user observations and summaries
- **Knowledge Base Search** — Search TAC knowledge bases with relevance scoring
- **Flex Escalation** — Route conversations to human agents via Twilio Flex
- **Messaging** — Send messages through the conversation channel
- **Interstitial Filler** — Provide natural filler words during tool latency

### Conversation Flow

**Voice:** Incoming call -> TwiML -> WebSocket connection -> Agent created via factory -> Audio streamed bidirectionally -> Session persisted

**SMS:** Incoming message -> Webhook -> Session loaded (or created) -> Agent runs with message + memory context -> Response sent -> Session persisted

## API Reference

All public APIs are exported from the top-level `tac_azure` package:

```python
from tac_azure import (
    OmniChannelServer,
    OmniChannelHandler,
    AgentLike,
    SessionStore,
    InMemorySessionStore,
    ConversationSession,
    format_memory_context,
)
from tac_azure.tools import (
    create_memory_recall_tool,
    create_knowledge_tool,
    fetch_knowledge_base_info,
    KnowledgeBaseInfo,
    create_flex_escalation_tool,
    create_messaging_tool,
    interstitial_filler,
)
```

---

### `OmniChannelServer`

Batteries-included FastAPI server wrapping `OmniChannelHandler`. Pre-wires routes for TwiML, WebSocket, SMS webhooks, and health checks.

```python
server = OmniChannelServer(
    tac=tac,                          # TAC instance
    create_agent=create_agent,        # (ConversationSession) -> AgentLike
    channels=["voice", "sms"],        # Channels to enable (default: both)
    public_domain="example.ngrok.app",# Required when voice is enabled
    welcome_greeting="Hello!",        # Initial voice greeting
    on_message=None,                  # SMS message augmentation hook
    auto_retrieve_memory=True,        # Auto-retrieve memory on message arrival
    session_store=None,               # SessionStore impl (default: InMemorySessionStore)
    validate_webhooks=True,           # Validate Twilio webhook signatures
    websocket_path="/ws",             # WebSocket endpoint path
    twiml_path="/twiml",              # TwiML endpoint path
    sms_path="/webhook",              # SMS webhook endpoint path
    host="0.0.0.0",                   # Bind address
    port=8000,                        # Bind port
    on_startup=None,                  # Async callback invoked once at startup
)
```

**Methods:**

| Method | Description |
|---|---|
| `serve()` | Start the server (blocking). |
| `await serve_async()` | Start the server asynchronously. |
| `stop()` | Initiate graceful shutdown. |

**Properties:**

| Property | Description |
|---|---|
| `app` | The underlying FastAPI application (lazily created). |
| `handler` | The underlying `OmniChannelHandler`. |

**Default Routes:**

| Route | Method | Channel | Description |
|---|---|---|---|
| `/twiml` | POST | Voice | Incoming call TwiML |
| `/ws` | WebSocket | Voice | Audio streaming |
| `/conversation-relay-callback` | POST | Voice | ConversationRelay callbacks |
| `/webhook` | POST | SMS | Incoming SMS webhook |
| `/health` | GET | — | Health check |

---

### `OmniChannelHandler`

Lower-level handler for integrating into your own FastAPI app. Use this when you need full control over routing, middleware, and lifecycle.

```python
handler = OmniChannelHandler(
    tac=tac,                          # TAC instance
    create_agent=create_agent,        # (ConversationSession) -> AgentLike
    channels=["voice", "sms"],        # Channels to enable (default: both)
    public_domain="example.ngrok.app",# Required when voice is enabled
    welcome_greeting="Hello!",        # Initial voice greeting
    on_message=None,                  # SMS message augmentation hook
    auto_retrieve_memory=True,        # Auto-retrieve memory on message arrival
    session_store=None,               # SessionStore impl (default: InMemorySessionStore)
    websocket_path="/ws",             # WebSocket path (used in TwiML generation)
)
```

**Methods:**

| Method | Description |
|---|---|
| `await handle_twiml_request(from_number, to_number, call_sid)` | Handle incoming TwiML request. Returns XML string. |
| `await handle_websocket_connection(websocket)` | Handle WebSocket connection for voice audio streaming. |
| `await handle_sms_webhook(webhook_data, idempotency_token=None)` | Handle incoming SMS webhook payload. |

---

### Protocols

#### `AgentLike`

Any object with an async `run` method satisfies this protocol. This covers agents created via `client.as_agent(...)`, custom wrappers, and test doubles.

```python
class AgentLike(Protocol):
    async def run(self, prompt: str, **kwargs: Any) -> Any: ...
```

#### `SessionStore`

Protocol for persisting `AgentSession` between requests. Enables conversation continuity across SMS messages and background persistence for voice sessions.

```python
class SessionStore(Protocol):
    async def load(self, session_id: str) -> AgentSession | None: ...
    async def save(self, session_id: str, session: AgentSession) -> None: ...
```

`InMemorySessionStore` is the default implementation. For horizontal scaling, implement `SessionStore` backed by Redis, CosmosDB, or another shared store. `AgentSession` supports serialization via `to_dict()` / `from_dict()`.

---

### Tools

All tool factory functions return plain functions that Agent Framework discovers via function name, docstring, and type annotations.

#### `create_memory_recall_tool(tac, session) -> Callable`

Creates a tool that queries TAC's Memora client for the current profile's memories.

```python
tool = create_memory_recall_tool(tac, session)
# Agent can call: recall_profile_memory(query="previous plan details")
# Returns: {"observations": [...], "summaries": [...], "sessions": [...]}
```

| Parameter | Type | Description |
|---|---|---|
| `tac` | `TAC` | TAC instance with `memora_client` initialized. |
| `session` | `ConversationSession` | Current conversation session. |

#### `create_knowledge_tool(tac, knowledge_base_id, description, ...) -> Callable`

Creates a tool that searches a TAC knowledge base.

```python
tool = create_knowledge_tool(
    tac=tac,
    knowledge_base_id="know_knowledgebase_...",
    description="Search Owl Internet FAQ and support articles.",
    name="search_owl_faq",  # optional, default: "search_knowledge_base"
    top_k=5,                # optional, number of results
)
# Agent can call: search_owl_faq(query="how to reset router")
# Returns: [{"content": ..., "knowledge_id": ..., "score": ...}, ...]
```

#### `fetch_knowledge_base_info(tac, knowledge_base_id) -> KnowledgeBaseInfo`

Fetches metadata from a knowledge base for dynamic tool naming.

```python
info = await fetch_knowledge_base_info(tac, kb_id)
tool = create_knowledge_tool(tac, kb_id, description=info.description, name=info.name)
```

Returns a `KnowledgeBaseInfo` dataclass with `name` and `description` fields.

#### `create_flex_escalation_tool(memory_client, config) -> Callable`

Creates a tool that escalates conversations to human agents via Twilio Flex.

```python
tool = create_flex_escalation_tool(tac.memora_client, tac.config)
# Agent can call: escalate_to_flex(params={"reason": "billing dispute", "priority": "high"})
```

#### `create_messaging_tool(memory_client, config) -> Callable`

Creates a tool for sending messages to conversation participants.

```python
tool = create_messaging_tool(tac.memora_client, tac.config)
# Agent can call: send_message(params={"to": "+1234567890", "message": "Your order shipped"})
```

#### `interstitial_filler(filler_words) -> AsyncGenerator`

Async generator tool that provides filler words during voice latency. Unlike the other tools, this is used directly (not via a factory function).

```python
tools = [interstitial_filler, ...]
# Agent can call: interstitial_filler(filler_words="Let me look that up for you...")
```

---

### Utilities

#### `format_memory_context(memory_response, user_message) -> str`

Formats TAC auto-retrieved memory as structured context prepended to the user message. Used as the default `on_message` behavior when no custom hook is provided.

```python
augmented = format_memory_context(memory_response, "What's my plan?")
# "[User Observations]\n- Prefers premium plan\n\n[User Message]\nWhat's my plan?"
```

---

## Companion Project

For AWS Strands agent integration with Twilio, see [strands-communications-twilio](https://github.com/twilio-internal/strands-communications-twilio).

## Development

### Install Development Dependencies

```sh
uv sync
```
