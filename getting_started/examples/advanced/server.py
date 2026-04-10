"""Owl Internet Voice + SMS Agent — advanced example.

Demonstrates the full feature set of AgentFrameworkConnector:

- Channel-aware system prompts (voice vs SMS)
- Custom tools (outage lookup)
- Knowledge base tool
- Memory recall tool
- on_message hook (prepend customer phone number)
- FileAgentSessionStore (file-based session persistence)
- on_conversation_ended hook (clean up session files)
- on_error hook (custom error responses)
"""

from __future__ import annotations

# Fix SSL certificate verification on macOS (must be before other imports)
import truststore
truststore.inject_into_ssl()

import logging
import os
from pathlib import Path

from agent_framework.azure import AzureOpenAIResponsesClient
from azure.identity.aio import DefaultAzureCredential
from dotenv import load_dotenv

from tac_azure import (
    TAC,
    TACConfig,
    TACFastAPIServer,
    AgentFrameworkConnector,
    FileAgentSessionStore,
    ConversationSession,
    format_memory_context,
)
from tac_azure.tools import create_knowledge_tool, create_memory_recall_tool

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

logger = logging.getLogger(__name__)

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
# System prompts — channel-aware
# ---------------------------------------------------------------------------

VOICE_SYSTEM_PROMPT = """You are Owl Internet's customer service assistant on a phone call.
Keep responses clear, concise, and conversational.
Use plain text only — no markdown, no lists, no special formatting."""

SMS_SYSTEM_PROMPT = """You are Owl Internet's customer service assistant over SMS.
Keep responses concise and formatted for text messaging.
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
knowledge_base_id = os.environ.get("TWILIO_TAC_KNOWLEDGE_BASE_ID")

# ---------------------------------------------------------------------------
# Agent factory — called once per voice call, once per SMS message
# ---------------------------------------------------------------------------


def create_agent(session: ConversationSession):
    prompt = VOICE_SYSTEM_PROMPT if session.channel == "voice" else SMS_SYSTEM_PROMPT

    tools = [create_memory_recall_tool(tac, session), look_up_outage_tool]
    if knowledge_base_id:
        tools.append(create_knowledge_tool(tac, knowledge_base_id=knowledge_base_id))

    return client.as_agent(
        name="OwlAgent",
        instructions=prompt,
        tools=tools,
    )


# ---------------------------------------------------------------------------
# Connector + Server
# ---------------------------------------------------------------------------

session_store = FileAgentSessionStore("/tmp/owl_sessions")


def on_message(user_message, context, memory_response):
    """Prepend the customer's phone number for context."""
    prefix = f"[Customer: {context.author_info.address if context.author_info else 'unknown'}]\n"
    return prefix + format_memory_context(memory_response, user_message)


def on_error(error, context):
    """Return a channel-appropriate error message."""
    logger.error("Agent error", extra={"conversation_id": context.conversation_id}, exc_info=error)
    if context.channel == "voice":
        return "I'm sorry, I'm having trouble right now. Please try again."
    return "Sorry, something went wrong. Please try again or call us for help."


def handle_conversation_ended(context: ConversationSession) -> None:
    """Clean up session files when a conversation closes.

    Voice agent/session cleanup is handled automatically by the connector.
    This callback handles application-level cleanup (session files on disk).
    """
    session_store.delete(context.conversation_id)
    logger.info("Session file cleaned up", extra={"conversation_id": context.conversation_id})


tac.on_conversation_ended(handle_conversation_ended)

connector = AgentFrameworkConnector(
    tac=tac,
    create_agent=create_agent,
    auto_retrieve_memory=True,
    on_message=on_message,
    on_error=on_error,
    session_store=session_store,
)

server = TACFastAPIServer(
    tac=tac,
    voice_channel=connector.voice_channel,
    messaging_channels=[connector.sms_channel],
)

if __name__ == "__main__":
    server.start()
