"""Memory recall tool for Agent Framework agents.

Ported from strands_communications.twilio.tools.memory — stripped of @tool decorator.
Agent Framework discovers tools from function name + docstring + type annotations.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from tac.core.logging import get_logger
from tac.models.session import ConversationSession

if TYPE_CHECKING:
    from tac import TAC

logger = get_logger(__name__)


def create_memory_recall_tool(
    tac: TAC,
    session: ConversationSession,
) -> Any:
    """
    Create a memory recall tool that uses TAC's Memora client.

    Returns a plain async function — no decorator needed. Agent Framework discovers
    tools from the function name, docstring, and type annotations.

    Args:
        tac: TAC instance (provides access to MemoryClient internally)
        session: Conversation session with conversation_id and profile_id

    Returns:
        Async function suitable for passing to Agent Framework's tools list.

    Raises:
        ValueError: If ``tac.memora_client`` is not initialised.
    """
    if tac.memora_client is None:
        raise ValueError(
            "TAC memora_client is not initialised. "
            "Ensure twilio_memory_config is provided in TACConfig."
        )

    async def recall_profile_memory(query: str) -> dict[str, Any]:
        """Recall relevant memories for the current profile.

        Search the user's stored memories for information relevant to the query.
        Use this to personalize conversations based on past interactions.

        Args:
            query: A description of what to search for in the user's memory.
        """
        logger.info(
            f"MEMORY | Searching for: {query}",
            conversation_id=session.conversation_id,
            profile_id=session.profile_id,
        )

        try:
            memory_response = await tac.memora_client.retrieve_memory(
                profile_id=session.profile_id,
                conversation_id=session.conversation_id,
                query=query,
            )

            result = memory_response.model_dump(by_alias=True, exclude_none=True)

            observations = result.get("observations", [])
            summaries = result.get("summaries", [])

            obs_count = len(observations)
            sum_count = len(summaries)
            memory_items = []
            if obs_count > 0:
                memory_items.append(f"{obs_count} observations")
            if sum_count > 0:
                memory_items.append(f"{sum_count} summaries")
            memory_summary = ", ".join(memory_items) if memory_items else "no memories"

            logger.info(
                f"MEMORY | Retrieved {memory_summary}",
                conversation_id=session.conversation_id,
                profile_id=session.profile_id,
            )

            if observations:
                obs_preview = "; ".join(str(obs)[:100] for obs in observations[:3])
                logger.info(
                    f"MEMORY_DATA | Observations: {obs_preview}",
                    conversation_id=session.conversation_id,
                    profile_id=session.profile_id,
                    observations=observations,
                )
            if summaries:
                sum_preview = "; ".join(str(s)[:100] for s in summaries[:3])
                logger.info(
                    f"MEMORY_DATA | Summaries: {sum_preview}",
                    conversation_id=session.conversation_id,
                    profile_id=session.profile_id,
                    summaries=summaries,
                )

            return result

        except Exception as e:
            logger.error(
                f"MEMORY | Error retrieving memories: {e}",
                conversation_id=session.conversation_id,
                profile_id=session.profile_id,
            )
            return {"observations": [], "summaries": [], "sessions": []}

    return recall_profile_memory
