"""Owl Internet omni-channel Agent — advanced example.

Demonstrates the full feature set of AgentFrameworkConnector:

- All messaging channels (SMS, Chat, RCS, WhatsApp) plus Voice
- Channel-aware system prompts (voice vs text)
- Per-call TwiML customization via on_inbound_call_twiml
- A welcome greeting set through VoiceChannelConfig.default_twiml_options
- Custom tools (outage lookup)
- Knowledge base tool
- Memory recall tool
- on_message hook (prepend customer phone number)
- Session persistence (FileAgentSessionStore, with CosmosDB option)
- on_conversation_ended hook (clean up session files)
- on_error hook (custom error responses)

RCS and WhatsApp are created only when their address is configured
(TWILIO_RCS_SENDER_ID / TWILIO_WHATSAPP_NUMBER); otherwise those channel
attributes are None. Their config args are optional (tuning only), like SMS.
"""

from __future__ import annotations

# Fix SSL certificate verification on macOS (must be before other imports)
import truststore

truststore.inject_into_ssl()

import asyncio
import logging
import os
from pathlib import Path

from agent_framework import Agent
from agent_framework.openai import OpenAIChatClient
from azure.identity.aio import DefaultAzureCredential
from dotenv import load_dotenv
from tac import TAC, TACConfig
from tac.channels.chat import ChatChannelConfig
from tac.channels.rcs import RCSChannelConfig
from tac.channels.sms import SMSChannelConfig
from tac.channels.voice import VoiceChannelConfig
from tac.channels.whatsapp import WhatsAppChannelConfig
from tac.models import TACMemoryResponse
from tac.models.session import ConversationSession
from tac.models.voice import TwiMLOptions, TwiMLRequest
from tac.server import TACFastAPIServer

from tac_microsoft import (
    AgentFrameworkConnector,
    FileAgentSessionStore,
    format_memory_context,
)
from tac_microsoft.agent_framework_tools import (
    create_knowledge_tool,
    create_memory_tool,
)

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Azure AI client
# ---------------------------------------------------------------------------

credential = DefaultAzureCredential()
client = OpenAIChatClient(
    credential=credential,
    azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
    model=os.environ.get("AZURE_AI_DEPLOYMENT_NAME", "gpt-4o"),
)

# ---------------------------------------------------------------------------
# System prompts — channel-aware
# ---------------------------------------------------------------------------

VOICE_SYSTEM_PROMPT = """You are Owl Internet's customer service assistant on a phone call.
Keep responses clear, concise, and conversational.
Use plain text only — no markdown, no lists, no special formatting."""

TEXT_SYSTEM_PROMPT = """You are Owl Internet's customer service assistant over text
messaging (SMS, chat, RCS, or WhatsApp).
Keep responses concise and formatted for messaging.
Use short paragraphs. Bullet points are OK."""

# ---------------------------------------------------------------------------
# Custom tools
# ---------------------------------------------------------------------------


def look_up_outage_tool(zip_code: str) -> str:
    """Check if there is a recent internet outage in a specific zip code."""
    return f"No reported outages in {zip_code}. Service is operating normally."


# ---------------------------------------------------------------------------
# TAC setup
# ---------------------------------------------------------------------------

tac = TAC(config=TACConfig.from_env())
knowledge_base_id = os.environ.get("TWILIO_KNOWLEDGE_BASE_ID")

# Build the knowledge tool once at startup — it doesn't depend on session state.
knowledge_tool = (
    asyncio.run(
        create_knowledge_tool(
            tac,
            knowledge_base_id,
            description="Search the knowledge base for relevant information.",
        )
    )
    if knowledge_base_id
    else None
)

# ---------------------------------------------------------------------------
# Agent factory — called once per voice call, once per SMS message
# ---------------------------------------------------------------------------


def create_agent(session: ConversationSession) -> Agent:
    prompt = VOICE_SYSTEM_PROMPT if session.channel == "voice" else TEXT_SYSTEM_PROMPT

    tools = [create_memory_tool(tac, session), look_up_outage_tool, knowledge_tool]

    return client.as_agent(
        name="OwlAgent",
        instructions=prompt,
        tools=[t for t in tools if t is not None],
    )


# ---------------------------------------------------------------------------
# Connector + Server
# ---------------------------------------------------------------------------

session_store = FileAgentSessionStore()

# To use CosmosDB instead (for horizontal scaling), uncomment below:
# from tac_microsoft import CosmosDBAgentSessionStore
# session_store = CosmosDBAgentSessionStore(
#     endpoint=os.environ["AZURE_COSMOS_ENDPOINT"],
#     credential=os.environ["AZURE_COSMOS_KEY"],
# )


def on_message(
    user_message: str,
    context: ConversationSession,
    memory_response: TACMemoryResponse | None,
) -> str:
    """Customize the user message with context before sending it to the agent."""
    prefix = f"[Customer: {context.author_info.address if context.author_info else 'unknown'}]\n"
    return prefix + format_memory_context(memory_response, user_message)


def on_error(error: Exception, context: ConversationSession) -> str:
    """Return a channel-appropriate error message."""
    logger.error("Agent error", extra={"conversation_id": context.conversation_id}, exc_info=error)
    if context.channel == "voice":
        return "I'm sorry, I'm having trouble right now. Please try again."
    return "Sorry, something went wrong. Please try again or call us for help."


async def handle_conversation_ended(context: ConversationSession) -> None:
    """Clean up sessions when a conversation closes.

    Voice agent/session cleanup is handled automatically by the connector.
    This callback handles application-level cleanup, e.g. if you want to delete the session from the session store.
    """
    await session_store.delete(context.conversation_id)
    logger.info("Session cleaned up", extra={"conversation_id": context.conversation_id})


tac.on_conversation_ended(handle_conversation_ended)

connector = AgentFrameworkConnector(
    tac=tac,
    create_agent=create_agent,
    on_message=on_message,
    on_error=on_error,
    voice_config=VoiceChannelConfig(
        # Disable auto memory for best latency; the agent uses the memory tool.
        memory_mode="never",
        # Applies to every inbound call unless a per-call customizer overrides it.
        default_twiml_options=TwiMLOptions(
            welcome_greeting="Thanks for calling Owl Internet! How can I help?",
        ),
    ),
    sms_config=SMSChannelConfig(memory_mode="always"),
    chat_config=ChatChannelConfig(memory_mode="always"),
    # RCS / WhatsApp channels are created when TWILIO_RCS_SENDER_ID /
    # TWILIO_WHATSAPP_NUMBER are set; these configs are optional tuning
    # (memory_mode etc.) and have no effect if the address isn't configured.
    rcs_config=RCSChannelConfig(memory_mode="always"),
    whatsapp_config=WhatsAppChannelConfig(memory_mode="always"),
    session_store=session_store,
)


# Per-call TwiML customization: greet Spanish-speaking callers in Spanish.
# Fields the callback sets override default_twiml_options and TAC defaults;
# unset fields fall through.
async def customize_inbound_twiml(request: TwiMLRequest) -> TwiMLOptions:
    if request.caller_country == "MX":
        return TwiMLOptions(
            language="es-MX",
            welcome_greeting="¡Gracias por llamar a Owl Internet! ¿Cómo puedo ayudarle?",
        )
    return TwiMLOptions()


connector.voice_channel.on_inbound_call_twiml(customize_inbound_twiml)

# Every messaging channel the connector exposes; RCS/WhatsApp are None when
# not enabled, so filter them out before handing the list to the server.
messaging_channels = [
    connector.sms_channel,
    connector.chat_channel,
    connector.rcs_channel,
    connector.whatsapp_channel,
]

server = TACFastAPIServer(
    tac=tac,
    voice_channel=connector.voice_channel,
    messaging_channels=[c for c in messaging_channels if c is not None],
)

if __name__ == "__main__":
    server.start()
