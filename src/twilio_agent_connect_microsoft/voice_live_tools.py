"""TAC tools for the Voice Live connector.

Each factory returns a ``TACTool`` instance that can be passed directly
to :class:`VoiceLiveConfig` — no conversion step needed.

Usage::

    from twilio_agent_connect_microsoft.voice_live_tools import (
        create_memory_tool,
        create_knowledge_tool,
    )

    tools = [
        create_memory_tool(tac, session),
        await create_knowledge_tool(tac, kb_id),
        my_custom_tac_tool,  # TACTool from @function_tool
    ]

    config = VoiceLiveConfig(..., tools=[t for t in tools if t])
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from . import _tool_factories
from ._tool_factories import KnowledgeBaseInfo, fetch_knowledge_base_info

if TYPE_CHECKING:
    from tac import TAC
    from tac.models.session import ConversationSession
    from tac.tools.base import TACTool

__all__ = [
    "create_memory_tool",
    "create_knowledge_tool",
    "create_handoff_tool",
    "KnowledgeBaseInfo",
    "fetch_knowledge_base_info",
]


# ------------------------------------------------------------------
# Tool factories (return TACTool)
# ------------------------------------------------------------------


def create_memory_tool(
    tac: TAC,
    session: ConversationSession,
    *,
    name: str | None = None,
    description: str | None = None,
) -> TACTool | None:
    """Create a memory TACTool for Voice Live.

    Returns ``None`` if prerequisites are not met.
    """
    return _tool_factories.create_memory_tool(
        tac,
        session,
        name=name,
        description=description,
    )


async def create_knowledge_tool(
    tac: TAC,
    knowledge_base_id: str,
    *,
    name: str | None = None,
    description: str | None = None,
    top_k: int = 5,
) -> TACTool:
    """Create a knowledge base search TACTool for Voice Live.

    If ``name`` or ``description`` is omitted, fetches the knowledge base
    metadata to derive defaults.
    """
    return await _tool_factories.create_knowledge_tool(
        tac,
        knowledge_base_id,
        name=name,
        description=description,
        top_k=top_k,
    )


def create_handoff_tool(
    tac: TAC,
    session: ConversationSession,
    attributes: dict[str, Any] | None = None,
) -> TACTool:
    """Create a Studio handoff TACTool for Voice Live.

    Requires ``tac.config.studio_handoff_flow_sid`` to be set.
    """
    return _tool_factories.create_handoff_tool(tac, session, attributes)
