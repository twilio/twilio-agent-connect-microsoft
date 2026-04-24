"""Shared TACTool creation logic.

Internal module — not part of the public API.  Both
``agent_framework_tools`` and ``voice_live_tools`` delegate here
to create ``TACTool`` instances, then convert to the format their
connector expects.

All tool factories here are thin wrappers around ``tac.tools`` so
the Azure SDK stays aligned with core TAC behavior.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from tac.tools import (
    create_knowledge_tool as _core_create_knowledge_tool,
    create_memory_tool as _core_create_memory_tool,
    create_studio_handoff_tool as _core_create_studio_handoff_tool,
)

if TYPE_CHECKING:
    from tac import TAC
    from tac.models.session import ConversationSession
    from tac.tools.base import TACTool


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
    """
    if tac.knowledge_client is None:
        raise ValueError(
            "TAC knowledge_client is not initialised. "
            "Ensure memory_config is provided in TACConfig "
            "(knowledge client shares the same authentication)."
        )

    kb = await tac.knowledge_client.get_knowledge_base(knowledge_base_id)
    return KnowledgeBaseInfo(
        name=f"search_{kb.display_name.lower().replace(' ', '_').replace('-', '_')}",
        description=kb.description,
    )


# ------------------------------------------------------------------
# Memory — wraps tac.tools.create_memory_tool
# ------------------------------------------------------------------

def create_memory_tool(
    tac: TAC,
    session: ConversationSession,
    *,
    name: str | None = None,
    description: str | None = None,
) -> TACTool | None:
    """Create a memory tool by delegating to core TAC.

    Returns ``None`` when prerequisites are not met (no memory client
    or no ``profile_id``), so examples can filter with
    ``[t for t in tools if t]``.
    """
    if tac.conversation_memory_client is None:
        return None
    if not session.profile_id:
        return None

    return _core_create_memory_tool(
        conversation_memory_client=tac.conversation_memory_client,
        session=session,
        name=name,
        description=description,
    )


# ------------------------------------------------------------------
# Knowledge — wraps tac.tools.create_knowledge_tool
# ------------------------------------------------------------------

async def create_knowledge_tool(
    tac: TAC,
    knowledge_base_id: str,
    *,
    name: str | None = None,
    description: str | None = None,
    top_k: int = 5,
) -> TACTool:
    """Create a knowledge base search TACTool by delegating to core TAC.

    If ``name`` or ``description`` is omitted, core fetches the knowledge
    base metadata and derives defaults.
    """
    if not knowledge_base_id:
        raise ValueError("knowledge_base_id is required")
    if tac.knowledge_client is None:
        raise ValueError(
            "TAC knowledge_client is not initialised. "
            "Ensure memory_config is provided in TACConfig "
            "(knowledge client shares the same authentication)."
        )

    return await _core_create_knowledge_tool(
        knowledge_client=tac.knowledge_client,
        knowledge_base_id=knowledge_base_id,
        name=name,
        description=description,
        top_k=top_k,
    )


# ------------------------------------------------------------------
# Handoff — wraps tac.tools.create_studio_handoff_tool
# ------------------------------------------------------------------

def create_handoff_tool(
    tac: TAC,
    session: ConversationSession,
    attributes: dict[str, Any] | None = None,
) -> TACTool:
    """Create a Studio handoff TACTool by delegating to core TAC.

    Requires ``tac.config.studio_handoff_flow_sid`` to be set.
    """
    return _core_create_studio_handoff_tool(tac, session, attributes)
