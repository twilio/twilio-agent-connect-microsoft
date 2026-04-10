"""TAC tools for the Voice Live connector.

Each factory returns a ``TACTool`` instance.  Use :func:`prepare_tools`
to bulk-convert them into the ``(definitions, executors)`` pair that
:class:`VoiceLiveConfig` expects.

Usage::

    from tac_azure.voice_live_tools import (
        create_memory_recall_tool,
        create_knowledge_tool,
        prepare_tools,
    )

    tools = [
        create_memory_recall_tool(tac, session),
        create_knowledge_tool(tac, kb_id, description="..."),
        my_custom_tac_tool,  # TACTool from @function_tool
    ]
    definitions, executors = prepare_tools([t for t in tools if t])

    config = VoiceLiveConfig(..., tools=definitions, tool_executors=executors)
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from tac.tools.base import TACTool

from . import _tool_factories
from .tools.knowledge import KnowledgeBaseInfo, fetch_knowledge_base_info

if TYPE_CHECKING:
    from tac import TAC
    from tac.context.memory import MemoryClient
    from tac.core.config import TACConfig
    from tac.models.session import ConversationSession

__all__ = [
    "create_memory_recall_tool",
    "create_knowledge_tool",
    "create_flex_escalation_tool",
    "create_messaging_tool",
    "prepare_tools",
    "KnowledgeBaseInfo",
    "fetch_knowledge_base_info",
]


# ------------------------------------------------------------------
# Conversion helper
# ------------------------------------------------------------------

def prepare_tools(
    tools: list[TACTool],
) -> tuple[list[dict[str, Any]], dict[str, Callable[..., Awaitable[Any]]]]:
    """Convert a list of TACTools into Voice Live config format.

    Returns a ``(definitions, executors)`` tuple that can be passed
    directly to :class:`VoiceLiveConfig`::

        definitions, executors = prepare_tools(tools)
        config = VoiceLiveConfig(..., tools=definitions, tool_executors=executors)

    Args:
        tools: List of configured ``TACTool`` instances.

    Returns:
        Tuple of (tool definition dicts, name-to-executor mapping).
    """
    definitions: list[dict[str, Any]] = []
    executors: dict[str, Callable[..., Awaitable[Any]]] = {}
    for tool in tools:
        definitions.append(tool.to_openai_format())
        executors[tool.name] = tool.implementation
    return definitions, executors


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
