"""Memory recall tool — thin wrapper around TAC's create_memory_tool.

Uses TACTool.implementation to produce a clean callable that Agent Framework
auto-discovers from function name, docstring, and type annotations.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .._tool_factories import create_memory_recall_tool as _create

if TYPE_CHECKING:
    from tac import TAC
    from tac.models.session import ConversationSession


def create_memory_recall_tool(
    tac: TAC,
    session: ConversationSession,
) -> Any | None:
    """Create a memory recall tool backed by TAC's Conversation Memory client.

    Returns a plain async function suitable for Agent Framework's tools list.
    Delegates to TAC's ``create_memory_tool`` and extracts the
    ``.implementation`` callable so Agent Framework can auto-discover
    name, docstring, and parameter types.

    Returns ``None`` if the tool cannot be created (e.g. missing
    ``conversation_memory_client`` or ``profile_id``), allowing callers
    to safely use::

        tools = [t for t in [create_memory_recall_tool(tac, session), ...] if t]

    Args:
        tac: TAC instance (must have ``conversation_memory_client`` initialised).
        session: Conversation session with ``profile_id`` and ``conversation_id``.

    Returns:
        Async function ``recall_profile_memory(query: str) -> dict``, or
        ``None`` if prerequisites are not met.
    """
    tac_tool = _create(tac, session)
    return tac_tool.implementation if tac_tool else None
