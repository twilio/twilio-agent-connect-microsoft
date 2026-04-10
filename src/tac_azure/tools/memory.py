"""Memory recall tool — thin wrapper around TAC's create_memory_tool.

Uses TACTool.implementation to produce a clean callable that Agent Framework
auto-discovers from function name, docstring, and type annotations.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from tac.core.logging import get_logger
from tac.tools.memory import create_memory_tool as _tac_create_memory_tool

_logger = get_logger(__name__)

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
    if tac.conversation_memory_client is None:
        _logger.debug("Skipping memory tool: conversation_memory_client not initialised")
        return None

    if not session.profile_id:
        _logger.debug("Skipping memory tool: session has no profile_id")
        return None

    tac_tool = _tac_create_memory_tool(tac.conversation_memory_client, session)
    return tac_tool.implementation
