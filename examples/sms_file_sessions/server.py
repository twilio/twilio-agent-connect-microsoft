"""Owl Internet SMS Agent — with file-based session persistence.

Demonstrates how to implement a custom ``AgentSessionStore`` to persist
conversation sessions across SMS messages.  Sessions are stored as JSON
files on disk so conversation history survives server restarts.

Also demonstrates using TAC's ``on_conversation_ended`` hook to clean up
session files when a conversation closes.

This uses the Responses API (AzureOpenAIResponsesClient).  Agent Framework
auto-injects ``InMemoryHistoryProvider`` which stores messages in the
session state dict.  The ``FileAgentSessionStore`` persists that state to disk
between messages, giving multi-turn conversation memory.

For horizontal scaling, replace ``FileAgentSessionStore`` with an implementation
backed by a shared store (Redis, CosmosDB, etc.) — the ``AgentSessionStore``
protocol is the same.
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

from tac_azure import ConversationSession, OmniChannelServer
from tac_azure.tools import create_memory_recall_tool

load_dotenv()

logger = logging.getLogger(__name__)


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
# Agent setup
# ---------------------------------------------------------------------------

credential = DefaultAzureCredential()
client = AzureOpenAIResponsesClient(
    credential=credential,
    project_endpoint=os.environ["AZURE_AI_PROJECT_ENDPOINT"],
    deployment_name="gpt-4o",
)

SYSTEM_PROMPT = """You are Owl Internet's customer service assistant over SMS.
Keep responses concise and formatted for text messaging.
Use short paragraphs. Bullet points are OK."""

tac = TAC(config=TACConfig.from_env())
session_store = FileAgentSessionStore("/tmp/owl_sms_sessions")


# ---------------------------------------------------------------------------
# Clean up session files when conversations end
# ---------------------------------------------------------------------------


def handle_conversation_ended(context: ConversationSession) -> None:
    session_store.delete(context.conversation_id)
    logger.info("Session file cleaned up", extra={"conversation_id": context.conversation_id})


tac.on_conversation_ended(handle_conversation_ended)


def create_agent(session: ConversationSession):
    return client.as_agent(
        name="OwlSMSAgent",
        instructions=SYSTEM_PROMPT,
        tools=[create_memory_recall_tool(tac, session)],
    )


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------

server = OmniChannelServer(
    tac=tac,
    create_agent=create_agent,
    channels=["sms"],
    auto_retrieve_memory=True,
    session_store=session_store,
)

if __name__ == "__main__":
    server.serve()
