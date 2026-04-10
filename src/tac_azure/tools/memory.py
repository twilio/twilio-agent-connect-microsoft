"""Memory recall tool — thin wrapper around TAC's create_memory_tool.

Uses TACTool.implementation to produce a clean callable that Agent Framework
auto-discovers from function name, docstring, and type annotations.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from tac.tools.memory import create_memory_tool as _tac_create_memory_tool

if TYPE_CHECKING:
    from tac import TAC
    from tac.models.session import ConversationSession


def create_memory_recall_tool(
    tac: TAC,
    session: ConversationSession,
) -> Any:
    """Create a memory recall tool backed by TAC's Conversation Memory client.

    Returns a plain async function suitable for Agent Framework's tools list.
    Delegates to TAC's ``create_memory_tool`` and extracts the
    ``.implementation`` callable so Agent Framework can auto-discover
    name, docstring, and parameter types.

    Args:
        tac: TAC instance (must have ``conversation_memory_client`` initialised).
        session: Conversation session with ``profile_id`` and ``conversation_id``.

    Returns:
        Async function: ``recall_profile_memory(query: str) -> dict``

    Raises:
        ValueError: If ``tac.conversation_memory_client`` is not initialised.
    """
    if tac.conversation_memory_client is None:
        raise ValueError(
            "TAC conversation_memory_client is not initialised. "
            "Ensure twilio_memory_config is provided in TACConfig."
        )

    tac_tool = _tac_create_memory_tool(tac.conversation_memory_client, session)
    return tac_tool.implementation
