"""Shared TACTool creation logic.

Internal module — not part of the public API.  Both
``agent_framework_tools`` and ``voice_live_tools`` delegate here
to create ``TACTool`` instances, then convert to the format their
connector expects.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from typing import Annotated

from tac.context.memory import MemoryClient
from tac.core.logging import get_logger
from tac.tools.base import InjectedToolArg, TACTool, function_tool
from tac.tools.knowledge import search_knowledge

if TYPE_CHECKING:
    from tac import TAC
    from tac.core.config import TACConfig
    from tac.models.session import ConversationSession

_logger = get_logger(__name__)


# ------------------------------------------------------------------
# Knowledge base info helper
# ------------------------------------------------------------------

@dataclass
class KnowledgeBaseInfo:
    """Metadata fetched from a knowledge base."""

    name: str
    description: str


async def fetch_knowledge_base_info(
    tac: TAC,
    knowledge_base_id: str,
) -> KnowledgeBaseInfo:
    """Fetch name and description from a knowledge base.

    Useful when you want the LLM tool name/description to match the
    knowledge base configuration without hardcoding them.

    Args:
        tac: TAC instance.
        knowledge_base_id: The knowledge base ID
            (format: ``know_knowledgebase_*``).

    Returns:
        :class:`KnowledgeBaseInfo` with ``name`` and ``description``.

    Raises:
        ValueError: If ``tac.knowledge_client`` is not initialised.

    Example::

        info = await fetch_knowledge_base_info(tac, kb_id)
        tool = create_knowledge_tool(tac, kb_id, description=info.description, name=info.name)
    """
    if tac.knowledge_client is None:
        raise ValueError(
            "TAC knowledge_client is not initialised. "
            "Ensure twilio_memory_config is provided in TACConfig "
            "(knowledge client shares the same authentication)."
        )

    kb = await tac.knowledge_client.get_knowledge_base(knowledge_base_id)
    return KnowledgeBaseInfo(
        name=f"search_{kb.display_name.lower().replace(' ', '_').replace('-', '_')}",
        description=kb.description,
    )


# ------------------------------------------------------------------
# Memory
# ------------------------------------------------------------------

async def _retrieve_profile_memory(
    query: str,
    conversation_memory_client: Annotated[MemoryClient, InjectedToolArg],
    profile_id: Annotated[str, InjectedToolArg],
    conversation_id: Annotated[str | None, InjectedToolArg] = None,
) -> dict[str, Any]:
    """Search and retrieve relevant memories for the current profile.

    Performs semantic search across the user's conversation history, observations,
    and stored traits to find contextually relevant information.

    Args:
        query: What to search for in the user's memory (e.g., "preferences about food",
               "previous complaints", "contact information")

    Returns:
        Dictionary containing relevant memories, traits, and metadata
    """
    memory_response = await conversation_memory_client.retrieve_memory(
        profile_id=profile_id,
        conversation_id=conversation_id,
        query=query,
    )
    return memory_response.model_dump(by_alias=True, exclude_none=True)


def create_memory_recall_tool(
    tac: TAC,
    session: ConversationSession,
) -> TACTool | None:
    """Create a memory recall TACTool.

    Returns ``None`` when prerequisites are not met (no memory client
    or no ``profile_id``), allowing safe filtering with
    ``[t for t in tools if t]``.
    """
    if tac.conversation_memory_client is None:
        _logger.debug("Skipping memory tool: conversation_memory_client not initialised")
        return None

    if not session.profile_id:
        _logger.debug("Skipping memory tool: session has no profile_id")
        return None

    tool = function_tool()(_retrieve_profile_memory)
    return tool.configure_injection(
        conversation_memory_client=tac.conversation_memory_client,
        profile_id=session.profile_id,
        conversation_id=session.conversation_id,
    )


# ------------------------------------------------------------------
# Knowledge
# ------------------------------------------------------------------

def create_knowledge_tool(
    tac: TAC,
    knowledge_base_id: str,
    description: str,
    name: str = "search_knowledge_base",
    top_k: int = 5,
) -> TACTool:
    """Create a knowledge base search TACTool."""
    if not knowledge_base_id:
        raise ValueError("knowledge_base_id is required")
    if tac.knowledge_client is None:
        raise ValueError(
            "TAC knowledge_client is not initialised. "
            "Ensure twilio_memory_config is provided in TACConfig "
            "(knowledge client shares the same authentication)."
        )

    tac_tool = function_tool(name=name, description=description)(search_knowledge)
    tac_tool.configure_injection(
        knowledge_client=tac.knowledge_client,
        knowledge_base_id=knowledge_base_id,
        top_k=top_k,
    )
    return tac_tool


# ------------------------------------------------------------------
# Flex escalation
# ------------------------------------------------------------------

def create_flex_escalation_tool(
    memory_client: MemoryClient,
    config: TACConfig,
) -> TACTool:
    """Create a Flex escalation TACTool."""
    _logger_ref = _logger
    _memory_client = memory_client
    _config = config

    def escalate_to_flex(reason: str, priority: str = "normal") -> dict[str, Any]:
        """Escalate the conversation to a human agent via Twilio Flex.

        Use this tool when the user requests to speak with a human agent,
        or when the conversation requires human intervention.

        Args:
            reason: The reason for escalation.
            priority: Priority level (default: normal).
        """
        _logger_ref.debug(
            "[FLEX TOOL] Escalating to Flex",
            reason=reason,
            priority=priority,
        )
        result: dict[str, Any] = {"status": "escalated", "task_id": "placeholder"}
        _logger_ref.debug("[FLEX TOOL] Escalation initiated successfully")
        return result

    return function_tool()(escalate_to_flex)


# ------------------------------------------------------------------
# Messaging
# ------------------------------------------------------------------

def create_messaging_tool(
    memory_client: MemoryClient,
    config: TACConfig,
) -> TACTool:
    """Create a messaging TACTool."""
    _logger_ref = _logger
    _memory_client = memory_client
    _config = config

    def send_message(to: str, message: str) -> dict[str, Any]:
        """Send a message to a conversation participant.

        Use this tool to send a message to a specific recipient in the conversation.

        Args:
            to: The recipient of the message.
            message: The message content to send.
        """
        _logger_ref.debug(
            "[MSG TOOL] Sending message",
            to=to,
            message=message,
        )
        result: dict[str, Any] = {"status": "sent", "message_id": "placeholder"}
        _logger_ref.debug("[MSG TOOL] Message sent successfully")
        return result

    return function_tool()(send_message)
