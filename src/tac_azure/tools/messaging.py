"""Messaging tool for Agent Framework agents.

Agent Framework discovers tools from function name + docstring + type annotations.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .._tool_factories import create_messaging_tool as _create

if TYPE_CHECKING:
    from tac.context.memory import MemoryClient
    from tac.core.config import TACConfig


def create_messaging_tool(
    memory_client: MemoryClient,
    config: TACConfig,
) -> Any:
    """Create a messaging tool using the TAC memory client.

    Returns a plain function — no decorator needed. Agent Framework discovers
    tools from the function name, docstring, and type annotations.

    Args:
        memory_client: TAC MemoryClient instance for sending messages.
        config: TAC configuration.

    Returns:
        Function suitable for passing to Agent Framework's tools list.
    """
    return _create(memory_client, config).implementation
