## Introduction

Twilio communications tools and a native MultiChannel bridge for Microsoft Agent Framework, supporting ConversationRelay voice streaming and SMS. It enables you to:

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
- **Developer Velocity:** `AgentFrameworkConnector` owns agent lifecycle and session management; `TACServer` (from the `tac` package) handles HTTP/WebSocket routing.
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
- Uses `AgentFrameworkConnector` + `TACServer` with custom routes via `server.app`
- Full control over additional routes and middleware
- Custom landing page example

**[File-Based SMS Sessions](examples/sms_file_sessions/)**
- Custom `AgentSessionStore` implementation using JSON files
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

- **`AgentFrameworkConnector`** — Bridge handling agent lifecycle, session management, and streaming responses for voice and SMS channels. Exposes `voice_channel` and `sms_channel` for `TACServer` to wire up routing.
- **`TACServer`** (from `tac` package) — HTTP/WebSocket server with pre-wired routes for TwiML, WebSocket, SMS webhooks, and health checks.
- **`AgentSessionStore`** — Protocol enabling pluggable session persistence backends.

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
    AgentFrameworkConnector,
    AgentSessionStore,
    InMemoryAgentSessionStore,
    ConversationSession,
    format_memory_context,
)
from tac.server import TACServer
from agent_framework import Agent  # Agent type from MS Agent Framework
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

### `AgentFrameworkConnector`

Bridge for voice and SMS channels with Agent Framework agents. Owns agent lifecycle, session management, and streaming. Delegates HTTP/WebSocket routing to `TACServer`. Both channel instances are always created — pass whichever you need to `TACServer`.

```python
bridge = AgentFrameworkConnector(
    tac=tac,                          # TAC instance
    create_agent=create_agent,        # (ConversationSession) -> Agent
    on_message=None,                  # SMS hook: (msg, context, memory) -> str
    auto_retrieve_memory=False,       # Auto-retrieve memory on message arrival
    session_store=None,               # AgentSessionStore impl (default: InMemoryAgentSessionStore)
)
```

**Properties:**

| Property | Description |
|---|---|
| `voice_channel` | The `VoiceChannel` instance. Pass to `TACServer` to enable voice. |
| `sms_channel` | The `SMSChannel` instance. Pass to `TACServer` to enable SMS. |

---

### `TACServer`

HTTP/WebSocket server from the `tac` package. Handles TwiML, WebSocket, SMS webhooks, and health check routing.

```python
from tac.server import TACServer

server = TACServer(
    tac=tac,                          # TAC instance
    voice_channel=bridge.voice_channel,  # From AgentFrameworkConnector
    sms_channel=bridge.sms_channel,      # From AgentFrameworkConnector
    on_startup=None,                  # Async callback invoked once at startup
)
```

**Methods:**

| Method | Description |
|---|---|
| `start()` | Start the server (blocking). |

**Properties:**

| Property | Description |
|---|---|
| `app` | The underlying FastAPI application. Use to add custom routes. |

---

### `AgentSessionStore`

Protocol for persisting `AgentSession` between requests. Enables conversation continuity across SMS messages and background persistence for voice sessions.

```python
class AgentSessionStore(Protocol):
    async def load(self, session_id: str) -> AgentSession | None: ...
    async def save(self, session_id: str, session: AgentSession) -> None: ...
```

`InMemoryAgentSessionStore` is the default implementation. For horizontal scaling, implement `AgentSessionStore` backed by Redis, CosmosDB, or another shared store. `AgentSession` supports serialization via `to_dict()` / `from_dict()`.

---

### Tools

Tool factory functions return plain callables that Agent Framework auto-discovers via function name, docstring, and type annotations. Memory and knowledge tools delegate to TAC's tool primitives (`TACTool`) internally.

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

## `on_message` Hook

By default, TAC auto-retrieves memory before each SMS message and the bridge prepends it to the user prompt via `format_memory_context()`. The `on_message` hook lets you customize or replace this behavior.

**Signature:**

```python
def on_message(
    user_message: str,
    context: ConversationSession,
    memory_response: TACMemoryResponse | None,
) -> str:
    """Return the final prompt string passed to agent.run()."""
```

**Examples:**

```python
# Add custom context on top of default memory formatting
def on_message(user_message, context, memory_response):
    prefix = f"[Customer: {context.from_number}, Channel: {context.channel}]\n"
    return prefix + format_memory_context(memory_response, user_message)

# Skip memory formatting entirely (use the recall tool instead)
def on_message(user_message, context, memory_response):
    return user_message

bridge = AgentFrameworkConnector(..., on_message=on_message)
```

To disable memory *fetching* entirely (saves latency), set `auto_retrieve_memory=False` instead. The `on_message` hook still fires but `memory_response` will be `None`.

---

## Error Handling

### SMS

When `agent.run()` raises an exception during SMS processing, the bridge:
1. Logs the full traceback
2. Sends `"Sorry, something went wrong. Please try again."` to the user
3. Still persists the `AgentSession` (it may contain a newly created Foundry thread)

### Voice

When streaming fails mid-utterance, the bridge:
1. Logs the error
2. Cleans up the voice agent for that conversation
3. Raises the exception (TAC handles the WebSocket lifecycle)

Voice errors do **not** send a fallback message — the call continues and the user can speak again to retry.

---

## Companion Project

For AWS Strands agent integration with Twilio, see [strands-communications-twilio](https://github.com/twilio-internal/strands-communications-twilio).

## Development

### Install Development Dependencies

```sh
uv sync
```
