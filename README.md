# TAC Azure - Azure Integrations for Twilio Agent Connect

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Azure-specific connectors for [Twilio Agent Connect (TAC)](https://github.com/twilio-innovation/twilio-agent-connect-python), enabling seamless integration with Azure AI agent services.

## Features

- **AgentFrameworkConnector** - [Microsoft Agent Framework](https://github.com/microsoft/agent-framework) integration
  - Agent lifecycle management (voice + SMS)
  - Supports [Foundry Hosted Agents, Foundry Prompt Agents, Azure OpenAI (Responses API, Chat Completions), and other backends](http://learn.microsoft.com/en-us/agent-framework/agents/providers/?pivots=programming-language-python#provider-comparison)
  - Pluggable session persistence via `AgentSessionStore` protocol
  - Memory context injection and `on_message` / `on_error` hooks
- **VoiceLiveConnector** - [Azure AI Foundry Voice Live](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/voice-live) integration
  - Low-latency streaming inference over WebSocket
  - Server-side conversation state (no local session management)
  - Tool execution with async handlers
- Multi-channel support (SMS + Voice)
- Built-in TAC tools (memory recall, knowledge search, Flex escalation, messaging, interstitial filler)
- Getting-started deployment guide with Dockerfile and deployment helpers
- [`AgentSessionStore`](#agentsessionstore) implementations for in-memory and CosmosDB

## Installation

### With Agent Framework

```bash
pip install tac-azure[agent-framework,server]
```

### With Voice Live

```bash
pip install tac-azure[voice-live,server]
```

### Development

```bash
# Install with development tools (includes all connectors)
pip install tac-azure[dev]
```

## Configuration

TAC Azure requires TAC environment variables. See [TAC Configuration](https://github.com/twilio-innovation/twilio-agent-connect-python#configuration) for details.

### Required Environment Variables

```bash
# Azure AI (required)
AZURE_AI_PROJECT_ENDPOINT=https://your-project.openai.azure.com/

# Twilio Configuration
TWILIO_TAC_AUTH_TOKEN=your_auth_token
TWILIO_TAC_API_KEY=your_api_key          # Starts with SK
TWILIO_TAC_API_TOKEN=your_api_token      # Secret for API key
TWILIO_TAC_PHONE_NUMBER=+1234567890
TWILIO_TAC_CONVERSATION_CONFIGURATION_ID=conv_configuration_xxx

# Server Configuration (for Voice)
TWILIO_TAC_VOICE_PUBLIC_DOMAIN=your-domain.ngrok.io

# Optional
AZURE_AI_MODEL_DEPLOYMENT_NAME=gpt-4o
TWILIO_TAC_KNOWLEDGE_BASE_ID=kb_xxx
```

## Examples

Full examples available in [`getting_started/examples/`](getting_started/examples/):

- **`basic/`** - Minimal Agent Framework setup (~30 lines)
- **`advanced/`** - Full feature set (channel-aware prompts, tools, hooks, file-based session persistence)
- **`voice_live/`** - Azure AI Foundry Voice Live with tool calling

## AgentSessionStore

The `AgentSessionStore` protocol defines how Agent Framework sessions are persisted between requests, enabling conversation continuity across SMS messages and horizontal scaling for voice.

Three implementations are included:

- **`InMemoryAgentSessionStore`** — default, suitable for single-instance deployments
- **`FileAgentSessionStore`** — persists sessions as JSON files on disk (single-instance, local dev)
- **`CosmosDBAgentSessionStore`** — persists sessions in Azure Cosmos DB for NoSQL (horizontally scaled production). Requires the `cosmos` extra: `pip install tac-azure[cosmos]`

Implement the protocol to use any other backing store (Redis, DynamoDB, Postgres, etc.).

## Development

### Setup

```bash
# Clone repository
git clone https://github.com/twilio-innovation/azure-twilio-agent-connect-python.git
cd azure-twilio-agent-connect-python

# Install dependencies
uv sync --all-extras
```

### Getting Started

See [`getting_started/README.md`](getting_started/README.md) for the full setup and deployment guide.

## Dependencies

TAC Azure depends on:
- **twilio-agent-connect** - Core [Twilio Agent Connect](https://github.com/twilio-innovation/twilio-agent-connect-python) framework (installed from GitHub)
  - Requires `twilio-agent-connect[server]` extra for TACFastAPIServer support
- **agent-framework** (optional) - [Microsoft Agent Framework](https://github.com/microsoft/agent-framework)
- **websockets** (optional) - For Voice Live connector
- **azure-cosmos** (optional) - For CosmosDB session store

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

MIT License - see [LICENSE](LICENSE) file for details.
