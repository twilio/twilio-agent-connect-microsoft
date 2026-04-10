"""AgentSessionStore implementations for TAC Azure."""

from tac_azure.agent_framework_types import AgentSessionStore

from .file import FileAgentSessionStore
from .in_memory import InMemoryAgentSessionStore

__all__ = [
    "AgentSessionStore",
    "InMemoryAgentSessionStore",
    "FileAgentSessionStore",
    "CosmosDBAgentSessionStore",
]


def __getattr__(name: str) -> object:
    if name == "CosmosDBAgentSessionStore":
        from .cosmos import CosmosDBAgentSessionStore

        return CosmosDBAgentSessionStore
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
