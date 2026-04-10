# Getting Started with TAC Azure

Quick start guide for using TAC Azure with Microsoft Agent Framework.

## Installation

```bash
pip install tac-azure
```

## Environment Setup

Create a `.env` file with your credentials:

```bash
# Azure AI (required)
AZURE_AI_PROJECT_ENDPOINT=https://your-project.openai.azure.com/

# Twilio Configuration (required)
TWILIO_AUTH_TOKEN=your_auth_token
TWILIO_API_KEY=your_api_key
TWILIO_API_TOKEN=your_api_token
TWILIO_PHONE_NUMBER=+1234567890
TWILIO_CONVERSATION_SERVICE_SID=conv_configuration_xxx

# Server Configuration (for Voice)
TWILIO_TAC_VOICE_PUBLIC_DOMAIN=your-domain.ngrok.io

# Optional
TWILIO_TAC_KNOWLEDGE_BASE_ID=kb_xxx
```

## Examples

See [`examples/`](examples/) for complete working examples:

- **[`agent_framework/basic.py`](examples/agent_framework/basic.py)** — Minimal Agent Framework setup (~30 lines)
- **[`agent_framework/advanced.py`](examples/agent_framework/advanced.py)** — Full feature set (channel-aware prompts, tools, hooks, session persistence)
- **[`voice_live/basic.py`](examples/voice_live/basic.py)** — Voice Live with custom tools

## Quick Example

```python
import os

from agent_framework.azure import AzureOpenAIResponsesClient
from azure.identity.aio import DefaultAzureCredential
from dotenv import load_dotenv
from tac import TAC, TACConfig
from tac.server import TACFastAPIServer
from tac_azure import ConversationSession, AgentFrameworkConnector

load_dotenv()

tac = TAC(config=TACConfig.from_env())

credential = DefaultAzureCredential()
client = AzureOpenAIResponsesClient(
    credential=credential,
    project_endpoint=os.environ["AZURE_AI_PROJECT_ENDPOINT"],
    deployment_name="gpt-4o",
)

def create_agent(session: ConversationSession):
    return client.as_agent(name="MyAgent", instructions="You are helpful.")

connector = AgentFrameworkConnector(tac=tac, create_agent=create_agent)

server = TACFastAPIServer(
    tac=tac,
    voice_channel=connector.voice_channel,
    sms_channel=connector.sms_channel,
)
server.start()
```
