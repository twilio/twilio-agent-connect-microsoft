"""CosmosDB-based AgentSessionStore implementation."""

from __future__ import annotations

from typing import Any

from agent_framework import AgentSession
from azure.cosmos.aio import CosmosClient
from azure.cosmos import PartitionKey, exceptions


# Cosmos metadata fields to strip when loading sessions
_COSMOS_METADATA_KEYS = {"_rid", "_self", "_etag", "_ts", "_attachments"}


class CosmosDBAgentSessionStore:
    """Persist sessions in Azure Cosmos DB for NoSQL.

    Uses the async Cosmos client for non-blocking operations.
    The database and container are created automatically on first use
    via ``create_database_if_not_exists`` / ``create_container_if_not_exists``.

    Each session is stored as a document with ``id`` set to the
    ``session_id`` and partition key ``/id``, giving optimal point
    read/write performance.

    Args:
        endpoint: Cosmos DB account endpoint URL.
        credential: Account key (str) or Azure credential object
            (e.g. ``DefaultAzureCredential``).
        database_name: Database name (created if it doesn't exist).
        container_name: Container name (created if it doesn't exist).
        ttl: Optional time-to-live in seconds for session documents.
            When set, Cosmos automatically expires old sessions.

    Example::

        from azure.identity.aio import DefaultAzureCredential
        from tac_azure.stores import CosmosDBAgentSessionStore

        store = CosmosDBAgentSessionStore(
            endpoint="https://my-account.documents.azure.com:443/",
            credential=DefaultAzureCredential(),
            database_name="tac",
            container_name="sessions",
            ttl=86400,  # 24 hours
        )
        connector = AgentFrameworkConnector(tac=tac, ..., session_store=store)
    """

    def __init__(
        self,
        endpoint: str,
        credential: Any,
        database_name: str = "tac",
        container_name: str = "sessions",
        ttl: int | None = None,
    ) -> None:
        self._endpoint = endpoint
        self._credential = credential
        self._database_name = database_name
        self._container_name = container_name
        self._ttl = ttl
        self._client: CosmosClient | None = None
        self._container: Any = None

    async def _get_container(self) -> Any:
        """Lazily initialize the Cosmos client, database, and container."""
        if self._container is not None:
            return self._container

        self._client = CosmosClient(self._endpoint, credential=self._credential)
        database = await self._client.create_database_if_not_exists(self._database_name)

        container_kwargs: dict[str, Any] = {
            "id": self._container_name,
            "partition_key": PartitionKey(path="/id"),
        }
        if self._ttl is not None:
            container_kwargs["default_ttl"] = self._ttl

        self._container = await database.create_container_if_not_exists(**container_kwargs)
        return self._container

    async def load(self, session_id: str) -> AgentSession | None:
        """Load a session from Cosmos DB, or return None if not found."""
        container = await self._get_container()
        try:
            item = await container.read_item(item=session_id, partition_key=session_id)
        except exceptions.CosmosResourceNotFoundError:
            return None

        # Strip Cosmos metadata before deserializing
        for key in _COSMOS_METADATA_KEYS:
            item.pop(key, None)

        return AgentSession.from_dict(item)

    async def save(self, session_id: str, session: AgentSession) -> None:
        """Persist a session to Cosmos DB (upsert)."""
        container = await self._get_container()
        document: dict[str, Any] = {"id": session_id, **session.to_dict()}
        if self._ttl is not None:
            document["ttl"] = self._ttl
        await container.upsert_item(document)

    async def delete(self, session_id: str) -> None:
        """Delete a session from Cosmos DB if it exists."""
        container = await self._get_container()
        try:
            await container.delete_item(item=session_id, partition_key=session_id)
        except exceptions.CosmosResourceNotFoundError:
            pass

    async def close(self) -> None:
        """Close the async Cosmos client."""
        if self._client is not None:
            await self._client.close()
            self._client = None
            self._container = None
