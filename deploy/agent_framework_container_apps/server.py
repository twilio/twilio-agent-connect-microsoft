"""TAC Server with Agent Framework — Container Apps deployment.

This is a starting point. Edit the system prompt, tools, and agent
configuration below to match your use case.

For a full-featured example with channel-aware prompts, custom tools,
memory/knowledge tools, and error hooks, see:
    getting_started/examples/agent_framework/advanced.py
"""

from __future__ import annotations

import os

from agent_framework.openai import OpenAIChatClient
from azure.identity.aio import DefaultAzureCredential

from tac_microsoft import (
    TAC,
    TACConfig,
    TACFastAPIServer,
    AgentFrameworkConnector,
    CosmosDBAgentSessionStore,
    ConversationSession,
    SMSChannelConfig,
)

# ---------------------------------------------------------------------------
# Azure AI client (authenticates via Managed Identity)
# ---------------------------------------------------------------------------

credential = DefaultAzureCredential()
client = OpenAIChatClient(
    credential=credential,
    azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
    model=os.environ["AZURE_OPENAI_DEPLOYMENT_NAME"],
)

# ---------------------------------------------------------------------------
# System prompt — edit this
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a helpful customer service assistant.
Keep responses clear and concise."""

# ---------------------------------------------------------------------------
# Agent factory — edit this to add tools, change the model, etc.
# ---------------------------------------------------------------------------


def create_agent(session: ConversationSession):
    return client.as_agent(
        name="Agent",
        instructions=SYSTEM_PROMPT,
    )


# ---------------------------------------------------------------------------
# TAC + Connector + Server
# ---------------------------------------------------------------------------

tac = TAC(config=TACConfig.from_env())

# Cosmos DB session store (authenticates via Managed Identity)
session_store = CosmosDBAgentSessionStore(
    endpoint=os.environ["AZURE_COSMOS_ENDPOINT"],
    credential=credential,
)

connector = AgentFrameworkConnector(
    tac=tac,
    create_agent=create_agent,
    session_store=session_store,
    sms_config=SMSChannelConfig(memory_mode="always"),
)

server = TACFastAPIServer(
    tac=tac,
    voice_channel=connector.voice_channel,
    messaging_channels=[connector.sms_channel],
)

if __name__ == "__main__":
    server.start()
