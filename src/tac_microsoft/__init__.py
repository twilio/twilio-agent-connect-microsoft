"""TAC Microsoft integration — Azure connectors for Twilio Agent Connect.

This package is an **add-on** to core ``tac``: it ships the Azure-specific
pieces (connectors, session stores, the Voice Live types, the Hosted Agents
server) and depends on ``tac`` for everything else. Import core primitives
directly from ``tac``, and Azure pieces from ``tac_microsoft`` — the same
split the AWS sibling package uses::

    from tac import TAC, TACConfig                      # core
    from tac.channels.sms import SMSChannelConfig       # core
    from tac.server import TACFastAPIServer             # core
    from tac_microsoft import AgentFrameworkConnector   # Azure add-on

This keeps the two namespaces honest (where a symbol lives tells you which
package owns it) and means core additions never require a re-export here.
"""

from typing import TYPE_CHECKING

from .utils import format_memory_context

# Lazy imports for symbols that require optional extras.
# This lets `import tac_microsoft` succeed even when only core deps are installed.
# The TYPE_CHECKING block below is evaluated only by type checkers (mypy, IDEs)
# and mirrors what `__getattr__` resolves at runtime.
if TYPE_CHECKING:
    from .agent_framework_connector import AgentFrameworkConnector
    from .agent_framework_types import AgentSessionStore
    from .hosted_agents_server import StarletteWebSocketAdapter, TACHostedAgentsApp
    from .stores.cosmos import CosmosDBAgentSessionStore
    from .stores.file import FileAgentSessionStore
    from .stores.in_memory import InMemoryAgentSessionStore
    from .voice_live_connector import VoiceLiveConnector
    from .voice_live_types import VoiceLiveConfig, VoiceLiveError


def __getattr__(name: str) -> object:
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

    # Hosted Agents server — requires twilio-agent-connect-microsoft[hosted-agents] extra
    if name in ("TACHostedAgentsApp", "StarletteWebSocketAdapter"):
        from .hosted_agents_server import StarletteWebSocketAdapter, TACHostedAgentsApp

        return {
            "TACHostedAgentsApp": TACHostedAgentsApp,
            "StarletteWebSocketAdapter": StarletteWebSocketAdapter,
        }[name]

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
    # Connectors
    "AgentFrameworkConnector",
    "VoiceLiveConnector",
    "VoiceLiveConfig",
    "VoiceLiveError",
    # Hosted Agents server
    "TACHostedAgentsApp",
    "StarletteWebSocketAdapter",
    # Session stores
    "AgentSessionStore",
    "InMemoryAgentSessionStore",
    "FileAgentSessionStore",
    "CosmosDBAgentSessionStore",
    # Utilities
    "format_memory_context",
]
