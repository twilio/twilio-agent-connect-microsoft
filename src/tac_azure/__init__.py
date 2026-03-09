"""TAC Agent Framework integration.

Provides OmniChannelHandler and OmniChannelServer for building Twilio
voice and SMS agents with Microsoft Agent Framework.
"""

from tac.models.session import ConversationSession

from .omnichannel_handler import OmniChannelHandler
from .omnichannel_server import OmniChannelServer
from .types import InMemoryAgentSessionStore, AgentSessionStore
from .utils import format_memory_context

__all__ = [
    "ConversationSession",
    "AgentSessionStore",
    "InMemoryAgentSessionStore",
    "OmniChannelHandler",
    "OmniChannelServer",
    "format_memory_context",
]
