"""TAC tools for the Voice Live connector.

Each factory returns a ``TACTool`` instance that can be passed directly
to :class:`VoiceLiveConfig` — no conversion step needed.

Usage::

    from tac_azure.voice_live_tools import (
        create_memory_recall_tool,
        create_knowledge_tool,
    )

    tools = [
        create_memory_recall_tool(tac, session),
        create_knowledge_tool(tac, kb_id, description="..."),
        my_custom_tac_tool,  # TACTool from @function_tool
    ]

    config = VoiceLiveConfig(..., tools=[t for t in tools if t])
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from . import _tool_factories
from ._tool_factories import KnowledgeBaseInfo, fetch_knowledge_base_info

if TYPE_CHECKING:
    from tac import TAC
    from tac.context.memory import MemoryClient
    from tac.core.config import TACConfig
    from tac.models.session import ConversationSession
    from tac.tools.base import TACTool

__all__ = [
    "create_memory_recall_tool",
    "create_knowledge_tool",
    "create_flex_escalation_tool",
    "create_messaging_tool",
    "KnowledgeBaseInfo",
    "fetch_knowledge_base_info",
]


# ------------------------------------------------------------------
# Tool factories (return TACTool)
# ------------------------------------------------------------------

def create_memory_recall_tool(
    tac: TAC,
    session: ConversationSession,
) -> TACTool | None:
    """Create a memory recall TACTool for Voice Live.

    Returns ``None`` if prerequisites are not met.
    """
    return _tool_factories.create_memory_recall_tool(tac, session)


def create_knowledge_tool(
    tac: TAC,
    knowledge_base_id: str,
    description: str,
    name: str = "search_knowledge_base",
    top_k: int = 5,
) -> TACTool:
    """Create a knowledge base search TACTool for Voice Live."""
    return _tool_factories.create_knowledge_tool(
        tac, knowledge_base_id, description, name, top_k,
    )


def create_flex_escalation_tool(
    memory_client: MemoryClient,
    config: TACConfig,
) -> TACTool:
    """Create a Flex escalation TACTool for Voice Live."""
    return _tool_factories.create_flex_escalation_tool(memory_client, config)


def create_messaging_tool(
    memory_client: MemoryClient,
    config: TACConfig,
) -> TACTool:
    """Create a messaging TACTool for Voice Live."""
    return _tool_factories.create_messaging_tool(memory_client, config)
