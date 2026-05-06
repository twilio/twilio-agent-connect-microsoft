"""TAC tools for the Agent Framework connector.

Each factory returns a plain async callable that Agent Framework
auto-discovers from function name, docstring, and type annotations.

Usage::

    from tac_microsoft.agent_framework_tools import (
        create_memory_tool,
        create_knowledge_tool,
    )

    tools = [
        create_memory_tool(tac, session),
        await create_knowledge_tool(tac, kb_id),
    ]
    agent = client.as_agent(name="Agent", tools=[t for t in tools if t])
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, Any

from tac.core.logging import get_logger

from . import _tool_factories
from ._tool_factories import KnowledgeBaseInfo, fetch_knowledge_base_info

if TYPE_CHECKING:
    from tac import TAC
    from tac.models.session import ConversationSession

_logger = get_logger(__name__)

__all__ = [
    "create_memory_tool",
    "create_knowledge_tool",
    "create_handoff_tool",
    "interstitial_filler",
    "KnowledgeBaseInfo",
    "fetch_knowledge_base_info",
]


# ------------------------------------------------------------------
# Tool factories (return plain callables for Agent Framework)
# ------------------------------------------------------------------


def create_memory_tool(
    tac: TAC,
    session: ConversationSession,
    *,
    name: str | None = None,
    description: str | None = None,
) -> Any | None:
    """Create a memory tool for Agent Framework.

    Returns a plain async function, or ``None`` if prerequisites are
    not met (no memory client or ``profile_id``).
    """
    tool = _tool_factories.create_memory_tool(
        tac,
        session,
        name=name,
        description=description,
    )
    return tool.implementation if tool else None


async def create_knowledge_tool(
    tac: TAC,
    knowledge_base_id: str,
    *,
    name: str | None = None,
    description: str | None = None,
    top_k: int = 5,
) -> Any:
    """Create a knowledge base search tool for Agent Framework.

    If ``name`` or ``description`` is omitted, fetches the knowledge base
    metadata to derive defaults. Returns a plain async function.
    """
    tool = await _tool_factories.create_knowledge_tool(
        tac,
        knowledge_base_id,
        name=name,
        description=description,
        top_k=top_k,
    )
    return tool.implementation


def create_handoff_tool(
    tac: TAC,
    session: ConversationSession,
    attributes: dict[str, Any] | None = None,
) -> Any:
    """Create a Studio handoff tool for Agent Framework.

    Returns a plain async function. Requires
    ``tac.config.studio_handoff_flow_sid`` to be set.
    """
    return _tool_factories.create_handoff_tool(tac, session, attributes).implementation


# ------------------------------------------------------------------
# Interstitial filler (Agent Framework only)
# ------------------------------------------------------------------


async def interstitial_filler(filler_words: str) -> AsyncGenerator[dict[str, Any], None]:
    """Provide a short, conversational filler sentence to fill dead air latency.

    Use this tool to speak brief filler words while waiting for other tool
    results to keep the conversation flowing naturally.

    Args:
        filler_words: The creative, context-aware filler sentence to speak
            while waiting for tool results.
    """
    _logger.info(f"Invoked tool: interstitial_filler with {filler_words}")
    yield {
        "tool": "interstitial_filler",
        "output": filler_words,
        "last": True,
    }
