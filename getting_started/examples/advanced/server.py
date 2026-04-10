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

import json
import logging
import os
from pathlib import Path

from agent_framework import AgentSession
from agent_framework.azure import AzureOpenAIResponsesClient
from azure.identity.aio import DefaultAzureCredential
from dotenv import load_dotenv
from tac import TAC, TACConfig
from tac.server import TACFastAPIServer

from tac_azure import ConversationSession, AgentFrameworkConnector, format_memory_context
from tac_azure.tools import create_knowledge_tool, create_memory_recall_tool

load_dotenv()

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
# Custom AgentSessionStore — file-based persistence
# ---------------------------------------------------------------------------


class FileAgentSessionStore:
    """Persist sessions as JSON files on the local filesystem.

    Each session is written to ``{storage_dir}/{session_id}.json``
    using Agent Framework's built-in ``AgentSession.to_dict()`` /
    ``from_dict()`` serialisation.
    """

    def __init__(self, storage_dir: str | Path = "/tmp/tac_sessions") -> None:
        self._storage_dir = Path(storage_dir)
        self._storage_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, session_id: str) -> Path:
        return self._storage_dir / f"{session_id}.json"

    async def load(self, session_id: str) -> AgentSession | None:
        path = self._path(session_id)
        if not path.exists():
            return None
        data = json.loads(path.read_text())
        return AgentSession.from_dict(data)

    async def save(self, session_id: str, session: AgentSession) -> None:
        path = self._path(session_id)
        path.write_text(json.dumps(session.to_dict()))

    def delete(self, session_id: str) -> None:
        self._path(session_id).unlink(missing_ok=True)


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
    sms_channel=connector.sms_channel,
)

if __name__ == "__main__":
    server.start()
