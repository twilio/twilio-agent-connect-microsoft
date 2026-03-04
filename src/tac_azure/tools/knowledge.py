"""Knowledge base search tool for Agent Framework agents.

Ported from strands_communications.twilio.tools.knowledge — stripped of @tool decorator.
Agent Framework discovers tools from function name + docstring + type annotations.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from tac.core.logging import get_logger

if TYPE_CHECKING:
    from tac import TAC

logger = get_logger(__name__)


@dataclass
class KnowledgeBaseInfo:
    """Metadata fetched from a knowledge base."""

    name: str
    description: str


async def fetch_knowledge_base_info(
    tac: TAC,
    knowledge_base_id: str,
) -> KnowledgeBaseInfo:
    """Fetch name and description from a knowledge base.

    Useful when you want the LLM tool name/description to match the
    knowledge base configuration without hardcoding them.

    Args:
        tac: TAC instance.
        knowledge_base_id: The knowledge base ID
            (format: ``know_knowledgebase_*``).

    Returns:
        :class:`KnowledgeBaseInfo` with ``name`` and ``description``.

    Raises:
        ValueError: If ``tac.knowledge_client`` is not initialised.

    Example::

        info = await fetch_knowledge_base_info(tac, kb_id)
        tool = create_knowledge_tool(tac, kb_id, description=info.description, name=info.name)
    """
    if tac.knowledge_client is None:
        raise ValueError(
            "TAC knowledge_client is not initialised. "
            "Ensure twilio_memory_config is provided in TACConfig "
            "(knowledge client shares the same authentication)."
        )

    kb = await tac.knowledge_client.get_knowledge_base(knowledge_base_id)
    return KnowledgeBaseInfo(
        name=f"search_{kb.display_name.lower().replace(' ', '_').replace('-', '_')}",
        description=kb.description,
    )


def create_knowledge_tool(
    tac: TAC,
    knowledge_base_id: str,
    description: str,
    name: str = "search_knowledge_base",
    top_k: int = 5,
) -> Any:
    """Create a knowledge base search tool.

    Returns a plain async function — no decorator needed.  Agent Framework
    discovers tools from the function name, docstring, and type annotations.

    Args:
        tac: TAC instance (provides access to KnowledgeClient internally).
        knowledge_base_id: The knowledge base ID to search
            (format: ``know_knowledgebase_*``).
        description: Description of what this knowledge base contains.
            Helps the LLM decide when to use the tool.
        name: Tool function name (default: ``"search_knowledge_base"``).
        top_k: Number of results to return (default: 5).

    Returns:
        Async function suitable for passing to Agent Framework's tools list.

    Raises:
        ValueError: If ``knowledge_base_id`` is empty or
            ``tac.knowledge_client`` is not initialised.

    Example::

        tool = create_knowledge_tool(
            tac=tac,
            knowledge_base_id="know_knowledgebase_...",
            description="Search Owl Internet's FAQ and support articles.",
        )
        tools.append(tool)
    """
    if not knowledge_base_id:
        raise ValueError("knowledge_base_id is required")
    if tac.knowledge_client is None:
        raise ValueError(
            "TAC knowledge_client is not initialised. "
            "Ensure twilio_memory_config is provided in TACConfig "
            "(knowledge client shares the same authentication)."
        )

    knowledge_client = tac.knowledge_client

    async def search_knowledge_base(query: str) -> list[dict[str, Any]]:
        """Search the knowledge base with the given query.

        Args:
            query: The search query string (max 2048 characters).

        Returns:
            List of knowledge chunk results with content, knowledge_id,
            created_at, and score fields.
        """
        try:
            logger.debug(
                f"[KB TOOL] Searching knowledge base '{knowledge_base_id}' "
                f"with query: {query[:100]}..."
            )
            result = await knowledge_client.search_knowledge_base(
                knowledge_base_id=knowledge_base_id,
                query=query,
                top_k=top_k,
            )
            logger.debug(f"[KB TOOL] Found {len(result)} results from knowledge base")
            return [r.model_dump() for r in result]
        except Exception as e:
            logger.error(f"[KB TOOL] Error searching knowledge base: {e}", exc_info=True)
            raise

    search_knowledge_base.__name__ = name
    search_knowledge_base.__doc__ = (
        f"{description}\n\nArgs:\n    query: The search query string."
    )

    return search_knowledge_base
