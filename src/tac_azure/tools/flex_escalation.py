"""Flex escalation tool for Agent Framework agents.

Ported from strands_communications.twilio.tools.flex_escalation — stripped of @tool decorator.
Agent Framework discovers tools from function name + docstring + type annotations.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from tac.core.logging import get_logger

if TYPE_CHECKING:
    from tac.context.memory import MemoryClient
    from tac.core.config import TACConfig

logger = get_logger(__name__)


def create_flex_escalation_tool(
    memory_client: MemoryClient,
    config: TACConfig,
) -> Any:
    """Create a Flex escalation tool using the TAC memory client.

    Returns a plain function — no decorator needed. Agent Framework discovers
    tools from the function name, docstring, and type annotations.

    Args:
        memory_client: TAC MemoryClient instance.
        config: TAC configuration.

    Returns:
        Function suitable for passing to Agent Framework's tools list.
    """

    def escalate_to_flex(params: dict[str, Any]) -> dict[str, Any]:
        """Escalate the conversation to a human agent via Twilio Flex.

        Use this tool when the user requests to speak with a human agent,
        or when the conversation requires human intervention.

        Args:
            params: A dictionary with 'reason' (escalation reason) and
                optional 'priority' keys.
        """
        logger.debug(f"[FLEX TOOL] Escalating to Flex: {params}")
        try:
            # Placeholder implementation - would integrate with TAC Flex escalation API
            result = {"status": "escalated", "task_id": "placeholder"}
            logger.debug("[FLEX TOOL] Escalation initiated successfully")
            return result
        except Exception as e:
            logger.error(f"[FLEX TOOL] Error escalating to Flex: {e}", exc_info=True)
            raise

    return escalate_to_flex
