"""Utility functions for TAC Agent Framework integration."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tac.models.tac import TACMemoryResponse


def format_memory_context(
    memory_response: TACMemoryResponse | None,
    user_message: str,
) -> str:
    """Format TAC auto-retrieved memory into an augmented user message.

    TAC automatically retrieves relevant memories for the profile when a message
    arrives. This function formats those memories as structured context and
    prepends them to the user message so the agent has personalization context
    without needing a separate tool call.

    Args:
        memory_response: Auto-retrieved memory from TAC's on_message_ready callback.
            May be None if memory is not configured or no memories exist.
        user_message: The original user message.

    Returns:
        The user message, optionally prefixed with formatted memory context.
    """
    if not memory_response:
        return user_message

    sections = []

    if memory_response.observations:
        observations_text = "\n".join(f"- {obs}" for obs in memory_response.observations)
        sections.append(f"[User Observations]\n{observations_text}")

    if memory_response.summaries:
        summaries_text = "\n".join(f"- {summary}" for summary in memory_response.summaries)
        sections.append(f"[Conversation Summaries]\n{summaries_text}")

    if not sections:
        return user_message

    memory_context = "\n\n".join(sections)
    return f"{memory_context}\n\n[User Message]\n{user_message}"
