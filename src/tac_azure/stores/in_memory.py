"""In-memory AgentSessionStore implementation."""

from __future__ import annotations

from agent_framework import AgentSession


class InMemoryAgentSessionStore:
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
