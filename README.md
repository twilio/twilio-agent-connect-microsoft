<div align="center">
  <div>
    <img src="https://raw.githubusercontent.com/twilio/twilio-agent-connect-microsoft/main/logo.svg" alt="TAC Microsoft Logo" width="120" height="120">
  </div>

  <h1>
    TAC Microsoft
  </h1>

  <h2>
    Azure integrations for Twilio Agent Connect — connect Microsoft Foundry agents to Twilio's communication channels.
  </h2>

  <div align="center">
    <a href="https://github.com/twilio/twilio-agent-connect-microsoft"><img alt="Python SDK" src="https://img.shields.io/badge/Python-3.10+-3776AB.svg"/></a>
    <a href="https://github.com/twilio/twilio-agent-connect-microsoft/blob/main/LICENSE"><img alt="License" src="https://img.shields.io/badge/license-MIT-green.svg"/></a>
    <a href="https://github.com/twilio/twilio-agent-connect-microsoft/tree/main/getting_started/examples"><img alt="Getting Started" src="https://img.shields.io/badge/Getting%20Started-Examples-F22F46.svg"/></a>
  </div>
  
  <p>
    <a href="https://www.twilio.com/docs/platform/tac/overview">Documentation</a>
    ◆ <a href="https://github.com/twilio/twilio-agent-connect-python">Python SDK</a>
    ◆ <a href="https://github.com/twilio/twilio-agent-connect-microsoft/tree/main/getting_started/examples">Examples</a>
    ◆ <a href="https://github.com/twilio/twilio-agent-connect-microsoft/tree/main/deploy">Deployment</a>
  </p>
</div>

Azure-specific connectors for [Twilio Agent Connect (TAC)](https://github.com/twilio/twilio-agent-connect-python), enabling seamless integration with [Microsoft Foundry](https://learn.microsoft.com/en-us/azure/foundry/what-is-foundry) — including [Microsoft Agent Framework](https://github.com/microsoft/agent-framework) and the [Voice Live API](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/voice-live).

---

## Features

- **AgentFrameworkConnector** - [Microsoft Agent Framework](https://github.com/microsoft/agent-framework) integration
  - Agent lifecycle management (Voice + SMS + Chat)
  - Supports [Foundry Hosted Agents, Foundry Prompt Agents, Azure OpenAI (Responses API, Chat Completions), and other backends](https://learn.microsoft.com/en-us/agent-framework/agents/providers/?pivots=programming-language-python#provider-comparison)
  - Pluggable session persistence via `AgentSessionStore` protocol
  - Memory context injection and `on_message` / `on_error` hooks
- **VoiceLiveConnector** - [Voice Live API](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/voice-live) integration
  - Text-in / text-streaming-out over WebSocket (STT and TTS handled by Twilio Conversation Relay)
  - Server-side conversation state (no local session management)
  - Native interrupt handling via Voice Live `response.cancel` (server-side truncation of in-flight responses)
  - Tool execution with async handlers
- Multi-channel support (Voice + SMS + Chat)
- Built-in TAC tools (memory recall, knowledge search, Studio Flow handoff)
- Getting-started deployment guide with Dockerfile and deployment helpers
- [`AgentSessionStore`](#agentsessionstore) implementations for in-memory, file, and Cosmos DB

## Installation

### With Agent Framework

```bash
pip install twilio-agent-connect-microsoft[agent-framework,server]
```

### With Voice Live

```bash
pip install twilio-agent-connect-microsoft[voice-live,server]
```

### Development

```bash
git clone https://github.com/twilio/twilio-agent-connect-microsoft.git
cd twilio-agent-connect-microsoft
uv sync --all-extras
```

## Prerequisites

Before running any examples, you need to create and configure the required Twilio services (Conversation Configuration, phone number, etc.). Follow the [TAC Quickstart guide](https://www.twilio.com/docs/platform/tac/quickstart) to set these up.

## Configuration

TAC Microsoft requires TAC environment variables. See [TAC Configuration](https://github.com/twilio/twilio-agent-connect-python#configuration) for details.

### Required Environment Variables

```bash
# Twilio Agent Connect (required for all examples)
TWILIO_CONVERSATION_CONFIGURATION_ID=conv_configuration_xxxxxxxxxxxxxxxxxx
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your_auth_token
TWILIO_API_KEY=SKxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_API_SECRET=your_api_key_secret
TWILIO_PHONE_NUMBER=+1234567890

# Server (required for voice)
TWILIO_VOICE_PUBLIC_DOMAIN=your-domain.ngrok.io

# Azure OpenAI — Agent Framework basic example (API key auth)
# Endpoint is the resource base URL only — no /openai/v1 suffix.
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_AI_API_KEY=your_azure_openai_api_key
AZURE_AI_DEPLOYMENT_NAME=gpt-4o

# Agent Framework advanced example uses the same AZURE_OPENAI_ENDPOINT as basic,
# but authenticates via `DefaultAzureCredential` (run `az login` first) instead of an API key.

# Voice Live API — voice_live example (hostname only, no https:// prefix)
# AZURE_VOICE_LIVE_ENDPOINT=your-resource.services.ai.azure.com
# AZURE_VOICE_LIVE_API_KEY=your_voice_live_api_key
# AZURE_VOICE_LIVE_MODEL=gpt-realtime
```

See [`getting_started/examples/.env.example`](https://github.com/twilio/twilio-agent-connect-microsoft/blob/main/getting_started/examples/.env.example) for the full list including optional features (Cosmos DB, knowledge base, conversation intelligence). Copy it to `getting_started/examples/.env` and fill in your values — all examples load from that shared file.

## Quick Start

Everything imports from `tac_microsoft` — no need to import from the underlying `tac` package:

```python
from tac_microsoft import (
    TAC, TACConfig, TACFastAPIServer,
    AgentFrameworkConnector, ConversationSession,
    FileAgentSessionStore,
)
from tac_microsoft.agent_framework_tools import create_memory_tool
```

## Examples

Full examples available in [`getting_started/examples/`](https://github.com/twilio/twilio-agent-connect-microsoft/tree/main/getting_started/examples):

- **`agent_framework/basic.py`** - Minimal Agent Framework setup (~30 lines)
- **`agent_framework/advanced.py`** - Full feature set (channel-aware prompts, tools, hooks, session persistence)
- **`voice_live/basic.py`** - Voice Live API with tool calling

## AgentSessionStore

The `AgentSessionStore` protocol defines how Agent Framework sessions are persisted between requests, enabling conversation continuity across SMS messages and horizontal scaling for voice.

Three implementations are included:

- **`InMemoryAgentSessionStore`** — default, suitable for single-instance deployments
- **`FileAgentSessionStore`** — persists sessions as JSON files on disk (single-instance, local dev)
- **`CosmosDBAgentSessionStore`** — persists sessions in Azure Cosmos DB for NoSQL (horizontally scaled production). Requires the `cosmos` extra: `pip install twilio-agent-connect-microsoft[cosmos]`

Implement the protocol to use any other backing store (Redis, DynamoDB, Postgres, etc.).

## Development

### Setup

```bash
# Clone repository
git clone https://github.com/twilio/twilio-agent-connect-microsoft.git
cd twilio-agent-connect-microsoft

# Install dependencies
uv sync --all-extras
```

### Getting Started

See [`getting_started/README.md`](https://github.com/twilio/twilio-agent-connect-microsoft/blob/main/getting_started/README.md) for the full setup and deployment guide.

## Dependencies

TAC Microsoft depends on:
- **twilio-agent-connect** - Core [Twilio Agent Connect](https://pypi.org/project/twilio-agent-connect/) framework (installed from PyPI)
  - Requires `twilio-agent-connect[server]` extra for TACFastAPIServer support
- **agent-framework** (optional) - [Microsoft Agent Framework](https://github.com/microsoft/agent-framework)
- **websockets** (optional) - For Voice Live connector
- **azure-cosmos** (optional) - For CosmosDB session store

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

MIT License - see [LICENSE](https://github.com/twilio/twilio-agent-connect-microsoft/blob/main/LICENSE) file for details.
