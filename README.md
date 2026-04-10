# TAC Azure - Azure Integrations for Twilio Agent Connect

The `azure-twilio-agent-connect-python` package is a Twilio developed package that provides two connectors for integrating Twilio channels with Azure AI services:

- **AgentFrameworkConnector** — bridges Twilio voice and messaging channels to [Microsoft Agent Framework SDK](https://github.com/microsoft/agent-framework). Agent Framework is provider-agnostic, so this connector supports [Foundry Hosted Agents, Foundry Prompt Agents, Azure OpenAI (Responses API, Chat Completions), and other backends](http://learn.microsoft.com/en-us/agent-framework/agents/providers/?pivots=programming-language-python#provider-comparison).
- **VoiceLiveConnector** — bridges Twilio voice to [Azure AI Foundry Voice Live](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/voice-live)'s WebSocket API for low-latency streaming inference.

The package also includes a getting-started deployment guide, deployment scripts and helpers (e.g. Dockerfile), native TAC tools, and [`AgentSessionStore`](#agentsessionstore) interfaces implementations for in memory and CosmosDB.

Built on top of the core [Twilio Agent Connect (TAC)](https://github.com/twilio-innovation/twilio-agent-connect-python) Python SDK.

## Installation

```bash
# Install uv (if not already installed)
pip install uv

# Create and activate a virtual environment
uv venv
source .venv/bin/activate

# Install project dependencies
uv pip install .
```

## Configuration

TAC Azure requires TAC environment variables. See [TAC Configuration](https://github.com/twilio-innovation/twilio-agent-connect-python#configuration) for details.

### Required Environment Variables

```bash
# Azure AI (required)
AZURE_AI_PROJECT_ENDPOINT=https://your-project.openai.azure.com/

# Twilio Configuration
TWILIO_AUTH_TOKEN=your_auth_token
TWILIO_API_KEY=your_api_key
TWILIO_API_TOKEN=your_api_token
TWILIO_PHONE_NUMBER=+1234567890
TWILIO_CONVERSATION_SERVICE_SID=conv_configuration_xxx

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

- **`InMemoryAgentSessionStore`** — default, suitable for single-instance deployments
- **CosmosDB** — for horizontally scaled production deployments (coming soon)

Implement the protocol to use any backing store (Redis, DynamoDB, Postgres, etc.).

## Development

### Setup

```bash
# Clone repository
git clone https://github.com/twilio-innovation/azure-twilio-agent-connect-python.git
cd azure-twilio-agent-connect-python

# Install dependencies
uv sync
```

## Dependencies

TAC Azure depends on:
- **twilio-agent-connect** - Core [Twilio Agent Connect](https://github.com/twilio-innovation/twilio-agent-connect-python) framework (installed from GitHub)
  - Requires `twilio-agent-connect[server]` extra for TACFastAPIServer support
- **agent-framework** - Microsoft Agent Framework
- **agent-framework-azure-ai** - Azure AI backend for Agent Framework
- **azure-identity** - Azure credential management
