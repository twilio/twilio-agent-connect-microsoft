# Getting Started with Twilio Agent Connect for Microsoft

Quick start guide for using Twilio Agent Connect for Microsoft with Microsoft Agent Framework or Azure AI Foundry Voice Live.

## Prerequisites

Before running any examples, you need to create and configure the required Twilio services (Conversation Configuration, phone number, etc.). Follow the [TAC Quickstart guide](https://www.twilio.com/docs/platform/tac/quickstart) to set these up.

## Installation

### With Agent Framework

```bash
pip install twilio-agent-connect-microsoft[agent-framework,server]
```

### With Voice Live

```bash
pip install twilio-agent-connect-microsoft[voice-live,server]
```

### Development (from source)

```bash
git clone https://github.com/twilio/twilio-agent-connect-microsoft.git
cd twilio-agent-connect-microsoft
uv sync --all-extras
```

## Environment Setup

Copy the example `.env` file and fill in your values. From the repo root:

```bash
cp getting_started/examples/.env.example getting_started/examples/.env
```

All examples load from the shared `getting_started/examples/.env` file.

### Required Variables (all examples)

```bash
# Twilio Agent Connect
TWILIO_CONVERSATION_CONFIGURATION_ID=conv_configuration_xxxxxxxxxxxxxxxxxx
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your_auth_token
TWILIO_API_KEY=SKxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_API_SECRET=your_api_key_secret
TWILIO_PHONE_NUMBER=+1234567890

# Server (required for voice)
TWILIO_VOICE_PUBLIC_DOMAIN=your-domain.ngrok.io
```

### Agent Framework — `basic.py` (Azure OpenAI, API key auth)

`AZURE_OPENAI_ENDPOINT` must be the resource base URL only — strip any `/openai/v1` suffix (the Foundry portal sometimes shows the longer form).

```bash
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_AI_API_KEY=your_azure_openai_api_key
AZURE_AI_DEPLOYMENT_NAME=gpt-4o
```

### Agent Framework — `advanced.py` (Azure OpenAI, Entra ID auth)

Uses `DefaultAzureCredential` — run `az login` first.

```bash
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
# AZURE_AI_DEPLOYMENT_NAME=gpt-4o
```

### Voice Live Examples

```bash
# Hostname only — no https:// prefix
AZURE_VOICE_LIVE_ENDPOINT=your-resource.services.ai.azure.com
AZURE_VOICE_LIVE_API_KEY=your_voice_live_api_key
# AZURE_VOICE_LIVE_MODEL=gpt-realtime
```

See [`examples/.env.example`](examples/.env.example) for the full list including optional features (Cosmos DB, knowledge base, conversation intelligence). The link is relative to this `getting_started/README.md` file.

## Examples

See [`examples/`](examples/) for complete working examples:

- **[`agent_framework/basic.py`](examples/agent_framework/basic.py)** — Minimal Agent Framework setup (~30 lines)
- **[`agent_framework/advanced.py`](examples/agent_framework/advanced.py)** — Full feature set (channel-aware prompts, tools, hooks, session persistence)
- **[`voice_live/basic.py`](examples/voice_live/basic.py)** — Voice Live with custom tools

### Running Examples

Each example is a standalone FastAPI server. From the repo root:

**With uv:**

```bash
uv run getting_started/examples/agent_framework/basic.py
uv run getting_started/examples/agent_framework/advanced.py
uv run getting_started/examples/voice_live/basic.py
```

**With pip/python:**

```bash
python getting_started/examples/agent_framework/basic.py
python getting_started/examples/agent_framework/advanced.py
python getting_started/examples/voice_live/basic.py
```

For voice calls, you need a publicly accessible URL. Use [ngrok](https://ngrok.com/) to expose your local server:

```bash
ngrok http 8000
```

Set `TWILIO_VOICE_PUBLIC_DOMAIN` in your `.env` to the ngrok hostname (e.g. `abc123.ngrok.io`).

## Quick Example

```python
import os

from agent_framework.openai import OpenAIChatClient
from azure.identity.aio import DefaultAzureCredential
from dotenv import load_dotenv

from tac_microsoft import (
    TAC, TACConfig, TACFastAPIServer,
    AgentFrameworkConnector, ConversationSession,
)

load_dotenv()

tac = TAC(config=TACConfig.from_env())

credential = DefaultAzureCredential()
client = OpenAIChatClient(
    credential=credential,
    azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
    model="gpt-4o",
)

def create_agent(session: ConversationSession):
    return client.as_agent(name="MyAgent", instructions="You are helpful.")

connector = AgentFrameworkConnector(tac=tac, create_agent=create_agent)

server = TACFastAPIServer(
    tac=tac,
    voice_channel=connector.voice_channel,
    messaging_channels=[connector.sms_channel],
)
server.start()
```
