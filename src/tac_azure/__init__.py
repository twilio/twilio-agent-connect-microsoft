"""TAC Azure integration — connectors for Twilio channels."""

from tac.models.session import ConversationSession

from .utils import format_memory_context

# Lazy imports for optional-dependency connectors.
# AgentFrameworkConnector requires `tac-azure[agent-framework]`.
# VoiceLiveConnector requires `tac-azure[voice-live]`.


def __getattr__(name: str) -> object:
    if name in ("AgentFrameworkConnector", "AgentSessionStore", "InMemoryAgentSessionStore"):
        from .agent_framework_bridge import AgentFrameworkConnector
        from .types import AgentSessionStore, InMemoryAgentSessionStore

        return {
            "AgentFrameworkConnector": AgentFrameworkConnector,
            "AgentSessionStore": AgentSessionStore,
            "InMemoryAgentSessionStore": InMemoryAgentSessionStore,
        }[name]

    if name == "FileAgentSessionStore":
        from .stores.file import FileAgentSessionStore

        return FileAgentSessionStore

    if name == "CosmosDBAgentSessionStore":
        from .stores.cosmos import CosmosDBAgentSessionStore

        return CosmosDBAgentSessionStore

    if name in ("VoiceLiveConnector", "VoiceLiveConfig", "VoiceLiveError"):
        from .voice_live_connector import VoiceLiveConnector
        from .voice_live_types import VoiceLiveConfig, VoiceLiveError

        return {
            "VoiceLiveConnector": VoiceLiveConnector,
            "VoiceLiveConfig": VoiceLiveConfig,
            "VoiceLiveError": VoiceLiveError,
        }[name]

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "ConversationSession",
    "AgentSessionStore",
    "InMemoryAgentSessionStore",
    "FileAgentSessionStore",
    "CosmosDBAgentSessionStore",
    "AgentFrameworkConnector",
    "VoiceLiveConnector",
    "VoiceLiveConfig",
    "VoiceLiveError",
    "format_memory_context",
]
