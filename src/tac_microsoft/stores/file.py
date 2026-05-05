"""File-based AgentSessionStore implementation."""

from __future__ import annotations

import json
from pathlib import Path

from agent_framework import AgentSession


class FileAgentSessionStore:
    """Persist sessions as JSON files on the local filesystem.

    Each session is written to ``{storage_dir}/{session_id}.json``
    using Agent Framework's built-in ``AgentSession.to_dict()`` /
    ``from_dict()`` serialisation.

    Suitable for single-instance deployments and local development.
    For horizontal scaling, use :class:`CosmosDBAgentSessionStore` or
    another shared store.

    Args:
        storage_dir: Directory to store session files.
            Created automatically if it doesn't exist.
    """

    def __init__(self, storage_dir: str | Path = "/tmp/tac_sessions") -> None:
        self._storage_dir = Path(storage_dir)
        self._storage_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, session_id: str) -> Path:
        return self._storage_dir / f"{session_id}.json"

    async def load(self, session_id: str) -> AgentSession | None:
        """Load a session from disk, or return None if not found."""
        path = self._path(session_id)
        if not path.exists():
            return None
        data = json.loads(path.read_text())
        return AgentSession.from_dict(data)

    async def save(self, session_id: str, session: AgentSession) -> None:
        """Persist a session to disk as JSON."""
        path = self._path(session_id)
        path.write_text(json.dumps(session.to_dict()))

    async def delete(self, session_id: str) -> None:
        """Remove a session file if it exists."""
        self._path(session_id).unlink(missing_ok=True)
