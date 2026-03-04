"""Type definitions for TAC Agent Framework integration."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from agent_framework import AgentSession


@runtime_checkable
class AgentLike(Protocol):
    """Protocol defining the agent interface expected by OmniChannelHandler.

    Any object with an async ``run`` method accepting a prompt string
    satisfies this protocol.  This covers Microsoft Agent Framework agents
    (``client.as_agent(...)``), custom wrappers, and test doubles.
    """

    async def run(self, prompt: str, **kwargs: Any) -> Any: ...


@runtime_checkable
class SessionStore(Protocol):
    """Protocol for persisting AgentSession between requests.

    Implementations store and retrieve ``AgentSession`` objects keyed by
    ``session_id`` (which maps to TAC's ``conversation_id``).  This enables
    conversation continuity across SMS messages regardless of which
    provider is used:

    - **Foundry Agent Service**: persists the server-side ``thread_id``
      (stored as ``session.service_session_id``) so subsequent messages
      reuse the same thread.
    - **Responses API / Chat Completions**: persists session state
      (including message history from ``InMemoryHistoryProvider``) so
      conversation context is available across messages.

    The default :class:`InMemorySessionStore` works for single-instance
    deployments.  For horizontal scaling, provide an implementation
    backed by Redis, CosmosDB, or another shared store.  ``AgentSession``
    supports serialisation via ``to_dict()`` / ``from_dict()``.
    """

    async def load(self, session_id: str) -> AgentSession | None:
        """Load a previously saved session, or None if not found."""
        ...

    async def save(self, session_id: str, session: AgentSession) -> None:
        """Persist a session after an agent run."""
        ...


class InMemorySessionStore:
    """In-memory session store for single-instance deployments.

    Stores sessions in a plain dict.  Suitable for development and
    single-instance production.  For horizontal scaling, replace with
    a persistent implementation (Redis, CosmosDB, etc.).
    """

    def __init__(self) -> None:
        self._sessions: dict[str, AgentSession] = {}

    async def load(self, session_id: str) -> AgentSession | None:
        return self._sessions.get(session_id)

    async def save(self, session_id: str, session: AgentSession) -> None:
        self._sessions[session_id] = session


