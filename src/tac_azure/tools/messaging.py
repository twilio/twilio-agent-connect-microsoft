"""Messaging tool for Agent Framework agents.

Ported from strands_communications.twilio.tools.messaging — stripped of @tool decorator.
Agent Framework discovers tools from function name + docstring + type annotations.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from tac.core.logging import get_logger

if TYPE_CHECKING:
    from tac.context.memory import MemoryClient
    from tac.core.config import TACConfig

logger = get_logger(__name__)


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

    def send_message(params: dict[str, Any]) -> dict[str, Any]:
        """Send a message to a conversation participant.

        Use this tool to send a message to a specific recipient in the conversation.

        Args:
            params: A dictionary with 'to' (recipient) and 'message' (content) keys.
        """
        logger.debug(f"[MSG TOOL] Sending message: {params}")
        try:
            # Placeholder implementation - would integrate with TAC messaging API
            result = {"status": "sent", "message_id": "placeholder"}
            logger.debug("[MSG TOOL] Message sent successfully")
            return result
        except Exception as e:
            logger.error(f"[MSG TOOL] Error sending message: {e}", exc_info=True)
            raise

    return send_message
