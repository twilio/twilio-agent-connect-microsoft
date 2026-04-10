"""TAC tools for the Agent Framework connector.

Each factory returns a plain async callable that Agent Framework
auto-discovers from function name, docstring, and type annotations.

Usage::

    from tac_azure.agent_framework_tools import (
        create_memory_recall_tool,
        create_knowledge_tool,
    )

    tools = [
        create_memory_recall_tool(tac, session),
        create_knowledge_tool(tac, kb_id, description="..."),
    ]
    agent = client.as_agent(name="Agent", tools=[t for t in tools if t])
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from . import _tool_factories

# Re-exports (Agent Framework only)
from .tools.interstitials import interstitial_filler
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
    "interstitial_filler",
    "KnowledgeBaseInfo",
    "fetch_knowledge_base_info",
]


def create_memory_recall_tool(
    tac: TAC,
    session: ConversationSession,
) -> Any | None:
    """Create a memory recall tool for Agent Framework.

    Returns a plain async function, or ``None`` if prerequisites are
    not met (no memory client or ``profile_id``).
    """
    tool = _tool_factories.create_memory_recall_tool(tac, session)
    return tool.implementation if tool else None


def create_knowledge_tool(
    tac: TAC,
    knowledge_base_id: str,
    description: str,
    name: str = "search_knowledge_base",
    top_k: int = 5,
) -> Any:
    """Create a knowledge base search tool for Agent Framework.

    Returns a plain async function.
    """
    return _tool_factories.create_knowledge_tool(
        tac, knowledge_base_id, description, name, top_k,
    ).implementation


def create_flex_escalation_tool(
    memory_client: MemoryClient,
    config: TACConfig,
) -> Any:
    """Create a Flex escalation tool for Agent Framework.

    Returns a plain function.
    """
    return _tool_factories.create_flex_escalation_tool(
        memory_client, config,
    ).implementation


def create_messaging_tool(
    memory_client: MemoryClient,
    config: TACConfig,
) -> Any:
    """Create a messaging tool for Agent Framework.

    Returns a plain function.
    """
    return _tool_factories.create_messaging_tool(
        memory_client, config,
    ).implementation
