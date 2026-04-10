"""Knowledge base search tool — thin wrapper around TAC's tool primitives.

Uses TAC's ``search_knowledge`` function and ``function_tool`` decorator to
build a TACTool, then extracts ``.implementation`` for Agent Framework.

``create_knowledge_tool`` is sync.  Use the async ``fetch_knowledge_base_info``
helper separately if you need to pull name/description from the KB at startup.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .._tool_factories import create_knowledge_tool as _create

if TYPE_CHECKING:
    from tac import TAC


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
    """Create a knowledge base search tool backed by TAC's KnowledgeClient.

    Returns a plain async function suitable for Agent Framework's tools list.
    Uses TAC's ``search_knowledge`` function with dependency injection,
    then extracts ``.implementation`` for Agent Framework auto-discovery.

    Args:
        tac: TAC instance (must have ``knowledge_client`` initialised).
        knowledge_base_id: The knowledge base ID to search
            (format: ``know_knowledgebase_*``).
        description: Description of what this knowledge base contains.
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
    return _create(tac, knowledge_base_id, description, name, top_k).implementation
