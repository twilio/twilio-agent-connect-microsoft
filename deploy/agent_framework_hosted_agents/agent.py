"""TAC Server with Agent Framework — Hosted Agents in Foundry Agent Service.

Runs inside the Hosted Agents runtime
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
from tac import TAC, TACConfig
from tac.channels.sms import SMSChannelConfig
from tac.models.session import ConversationSession

from tac_microsoft import (
    AgentFrameworkConnector,
    FileAgentSessionStore,
    TACHostedAgentsApp,
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
    # To also serve RCS and/or WhatsApp, set TWILIO_RCS_SENDER_ID /
    # TWILIO_WHATSAPP_NUMBER (the connector creates those channels when the
    # address is configured) and add connector.rcs_channel /
    # connector.whatsapp_channel to messaging_channels below. The *_config
    # args are optional tuning:
    # from tac.channels.chat import ChatChannelConfig
    # from tac.channels.rcs import RCSChannelConfig
    # from tac.channels.whatsapp import WhatsAppChannelConfig
    # chat_config=ChatChannelConfig(memory_mode="always"),
    # rcs_config=RCSChannelConfig(memory_mode="always"),
    # whatsapp_config=WhatsAppChannelConfig(memory_mode="always"),
)

server = TACHostedAgentsApp(
    tac=tac,
    voice_channel=connector.voice_channel,
    # Add connector.chat_channel / rcs_channel / whatsapp_channel here once
    # enabled above (filter out any that are None).
    messaging_channels=[connector.sms_channel],
)


if __name__ == "__main__":
    server.start()
