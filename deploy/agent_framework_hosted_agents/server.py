"""TAC Server with Agent Framework — Azure Hosted Agents deployment.

Runs inside Azure AI Foundry's Hosted Agents runtime
(``InvocationAgentServerHost``), behind APIM. APIM handles HMAC validation,
form → JSON transformation, and ``agent_session_id`` injection so the
sandbox-affinity contract works for Twilio retries and Conversation Relay
upgrades.

This is a starting point. Edit the system prompt, tools, and agent
configuration below to match your use case.

For a full-featured example with channel-aware prompts, custom tools,
memory/knowledge tools, and error hooks, see:
    getting_started/examples/agent_framework/advanced.py
"""

from __future__ import annotations

import os
from pathlib import Path

from agent_framework import Agent
from agent_framework.openai import OpenAIChatClient

from tac_microsoft import (
    TAC,
    AgentFrameworkConnector,
    ConversationSession,
    FileAgentSessionStore,
    SMSChannelConfig,
    TACConfig,
    TACHostedAgentsServer,
)

# ---------------------------------------------------------------------------
# Azure OpenAI client
# ---------------------------------------------------------------------------
# In production, prefer ``DefaultAzureCredential`` over an API key — drop the
# ``api_key`` argument and pass ``credential=DefaultAzureCredential()``.

_client = OpenAIChatClient(
    azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
    api_key=os.environ["AZURE_OPENAI_API_KEY"],
    model=os.environ["AZURE_OPENAI_DEPLOYMENT_NAME"],
)

# ---------------------------------------------------------------------------
# System prompt — edit this
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a helpful Twilio assistant. Keep replies short
(1–2 sentences for voice, <320 chars for SMS), clear, and friendly. Avoid
markdown and emoji. Spell out numbers and acronyms naturally so they read
well via text-to-speech. Reference prior context from the conversation
when appropriate."""


# ---------------------------------------------------------------------------
# Agent factory — edit this to add tools, change the model, etc.
# ---------------------------------------------------------------------------


def create_agent(session: ConversationSession) -> Agent:
    return _client.as_agent(name="TwilioAgent", instructions=SYSTEM_PROMPT)


# ---------------------------------------------------------------------------
# TAC + connector + server
# ---------------------------------------------------------------------------
# ``$HOME`` is the only filesystem path Hosted Agents preserves across the
# 15-minute idle eviction. Combined with ``agent_session_id`` sandbox
# affinity (set by APIM upstream), this gives durable session continuity
# without needing Cosmos DB.

tac = TAC(config=TACConfig.from_env())

session_dir = Path(os.environ["HOME"]) / "tac_sessions"

connector = AgentFrameworkConnector(
    tac=tac,
    create_agent=create_agent,
    session_store=FileAgentSessionStore(storage_dir=session_dir),
    sms_config=SMSChannelConfig(memory_mode="always"),
)

server = TACHostedAgentsServer(
    tac=tac,
    voice_channel=connector.voice_channel,
    messaging_channels=[connector.sms_channel],
)


if __name__ == "__main__":
    server.start()
