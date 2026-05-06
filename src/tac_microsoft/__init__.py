"""TAC Microsoft integration — connectors for Twilio channels.

Re-exports everything from the core ``tac`` package so developers can
import from a single namespace::

    from tac_microsoft import TAC, TACConfig, TACFastAPIServer, AgentFrameworkConnector
"""

# Re-export all public symbols from core TAC. Kept explicit (no star import) so
# the public surface is statically visible to linters, IDEs, and type checkers.
# If core TAC adds a new top-level export, add it here too.
from tac import (
    TAC,
    PartnerConnector,
    TACConfig,
    TwiMLOptions,
    get_logger,
)
from tac.channels.chat import ChatChannelConfig
from tac.channels.sms import SMSChannelConfig
from tac.channels.voice import VoiceChannelConfig
from tac.models.session import ConversationSession

from .utils import format_memory_context

# Lazy imports for symbols that require optional extras.
# This lets `import tac_microsoft` succeed even when only core deps are installed.


def __getattr__(name: str) -> object:
    # tac.server — requires twilio-agent-connect-microsoft[server] extra (fastapi, uvicorn)
    if name == "TACFastAPIServer":
        from tac.server import TACFastAPIServer

        return TACFastAPIServer

    # Agent Framework connector — requires twilio-agent-connect-microsoft[agent-framework] extra
    if name in ("AgentFrameworkConnector", "AgentSessionStore", "InMemoryAgentSessionStore"):
        from .agent_framework_connector import AgentFrameworkConnector
        from .agent_framework_types import AgentSessionStore
        from .stores.in_memory import InMemoryAgentSessionStore

        return {
            "AgentFrameworkConnector": AgentFrameworkConnector,
            "AgentSessionStore": AgentSessionStore,
            "InMemoryAgentSessionStore": InMemoryAgentSessionStore,
        }[name]

    # Session stores — FileAgentSessionStore requires agent-framework,
    # CosmosDBAgentSessionStore requires agent-framework + cosmos extras
    if name == "FileAgentSessionStore":
        from .stores.file import FileAgentSessionStore

        return FileAgentSessionStore

    if name == "CosmosDBAgentSessionStore":
        from .stores.cosmos import CosmosDBAgentSessionStore

        return CosmosDBAgentSessionStore

    # Voice Live connector — requires twilio-agent-connect-microsoft[voice-live] extra
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
    # Re-exported from tac core
    "TAC",
    "TACConfig",
    "TACFastAPIServer",
    "TwiMLOptions",
    "ConversationSession",
    "VoiceChannelConfig",
    "SMSChannelConfig",
    "ChatChannelConfig",
    "PartnerConnector",
    "get_logger",
    # Connectors
    "AgentFrameworkConnector",
    "VoiceLiveConnector",
    "VoiceLiveConfig",
    "VoiceLiveError",
    # Session stores
    "AgentSessionStore",
    "InMemoryAgentSessionStore",
    "FileAgentSessionStore",
    "CosmosDBAgentSessionStore",
    # Utilities
    "format_memory_context",
]
