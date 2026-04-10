"""AgentSessionStore implementations for TAC Azure."""

from tac_azure.types import AgentSessionStore, InMemoryAgentSessionStore

from .file import FileAgentSessionStore

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
