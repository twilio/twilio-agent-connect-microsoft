"""Interstitial filler tool for Agent Framework agents.

Ported from strands_communications.twilio.tools.interstitials — stripped of @tool decorator.
Agent Framework discovers tools from function name + docstring + type annotations.
"""

from __future__ import annotations

from typing import Any, AsyncGenerator

from tac.core.logging import get_logger

logger = get_logger(__name__)


async def interstitial_filler(filler_words: str) -> AsyncGenerator[dict[str, Any], None]:
    """Provide a short, conversational filler sentence to fill dead air latency.

    Use this tool to speak brief filler words while waiting for other tool
    results to keep the conversation flowing naturally.

    Args:
        filler_words: The creative, context-aware filler sentence to speak
            while waiting for tool results.
    """
    logger.info(f"Invoked tool: interstitial_filler with {filler_words}")
    yield {
        "tool": "interstitial_filler",
        "output": filler_words,
        "last": True,
    }
