"""Owl Internet Voice + SMS Agent — minimal example.

The simplest possible setup using AgentFrameworkConnector with the
Azure OpenAI Responses API.  Voice and SMS share a single system prompt.
"""

# Fix SSL certificate verification on macOS (must be before other imports)
import truststore
truststore.inject_into_ssl()

import os

from agent_framework.azure import AzureOpenAIResponsesClient
from azure.identity.aio import DefaultAzureCredential
from dotenv import load_dotenv
from pathlib import Path

from tac_azure import (
    TAC,
    TACConfig,
    TACFastAPIServer,
    AgentFrameworkConnector,
    ConversationSession,
)

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

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
# TAC setup
# ---------------------------------------------------------------------------

tac = TAC(config=TACConfig.from_env())


# ---------------------------------------------------------------------------
# Agent factory
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are Owl Internet's customer service assistant.
Keep responses clear and concise."""

def create_agent(session: ConversationSession):
    """Return an Agent Framework agent for this conversation.

    Called once at the start of a voice call, and on every incoming
    message for text channels (SMS, chat, etc.).

    ``session`` carries Twilio conversation context: channel type,
    conversation ID, caller/customer profile, and metadata.
    """
    return client.as_agent(
        name="OwlAgent",
        instructions=SYSTEM_PROMPT,
    )


# ---------------------------------------------------------------------------
# Connector + Server
# ---------------------------------------------------------------------------

connector = AgentFrameworkConnector(
    tac=tac,
    create_agent=create_agent,
)

server = TACFastAPIServer(
    tac=tac,
    voice_channel=connector.voice_channel,
    messaging_channels=[connector.sms_channel],
)

if __name__ == "__main__":
    server.start()
