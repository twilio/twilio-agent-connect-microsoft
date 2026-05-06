"""Owl Internet Voice + SMS Agent — minimal example.

The simplest possible setup using AgentFrameworkConnector with the
Azure OpenAI Responses API.  Voice and SMS share a single system prompt.
"""

# Fix SSL certificate verification on macOS (must be before other imports)
import truststore

truststore.inject_into_ssl()

import os
from pathlib import Path

from agent_framework import Agent
from agent_framework.openai import OpenAIChatClient
from dotenv import load_dotenv

from tac_microsoft import (
    TAC,
    AgentFrameworkConnector,
    ConversationSession,
    SMSChannelConfig,
    TACConfig,
    TACFastAPIServer,
)

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# ---------------------------------------------------------------------------
# Azure AI client
# ---------------------------------------------------------------------------

client = OpenAIChatClient(
    azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
    api_key=os.environ["AZURE_AI_API_KEY"],
    model=os.environ.get("AZURE_AI_DEPLOYMENT_NAME"),
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


def create_agent(session: ConversationSession) -> Agent:
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
    # Auto retrieve Twilio memory and inject into user message passed to AI agent for SMS
    sms_config=SMSChannelConfig(memory_mode="always"),
)

server = TACFastAPIServer(
    tac=tac,
    voice_channel=connector.voice_channel,
    messaging_channels=[connector.sms_channel],
)

if __name__ == "__main__":
    server.start()
