# TAC Azure - Azure Integrations for Twilio Agent Connect

Azure-specific connectors for [Twilio Agent Connect (TAC)](https://github.com/twilio-internal/twilio-agent-connect-python), enabling seamless integration with Azure AI agent services.

## Features

- **AgentFrameworkConnector** - Microsoft Agent Framework integration
  - Agent lifecycle management (voice + SMS)
  - Pluggable session persistence via `AgentSessionStore` protocol
  - Memory context injection and `on_message` / `on_error` hooks
- **VoiceLiveConnector** - Azure AI Foundry Voice Live integration
  - Streams text to and from Voice Live over WebSocket
  - Server-side conversation state (no local session management)
  - Tool execution with async handlers
- Multi-channel support (SMS + Voice)
- Built-in TAC tools (memory recall, knowledge search, Flex escalation, messaging, interstitial filler)

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

TAC Azure requires TAC environment variables. See [TAC Configuration](https://github.com/twilio-internal/twilio-agent-connect-python#configuration) for details.

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

## Development

### Setup

```bash
# Clone repository
git clone https://github.com/twilio-internal/azure-twilio-agent-connect-python.git
cd azure-twilio-agent-connect-python

# Install dependencies
uv sync
```

## Dependencies

TAC Azure depends on:
- **tac** - Core Twilio Agent Connect framework (installed from GitHub)
  - Requires `tac[server]` extra for TAC Server support
- **agent-framework** - Microsoft Agent Framework
- **agent-framework-azure-ai** - Azure AI backend for Agent Framework
- **azure-identity** - Azure credential management
