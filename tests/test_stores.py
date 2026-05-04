"""Tests for AgentSessionStore implementations."""

from __future__ import annotations

from pathlib import Path

import pytest
from agent_framework import AgentSession

from twilio_agent_connect_microsoft.stores.file import FileAgentSessionStore
from twilio_agent_connect_microsoft.stores.in_memory import InMemoryAgentSessionStore


class TestInMemoryAgentSessionStore:
    """Dict-backed, single-instance store."""

    async def test_load_returns_none_when_missing(self) -> None:
        store = InMemoryAgentSessionStore()
        assert await store.load("missing") is None

    async def test_save_then_load_roundtrip(self) -> None:
        store = InMemoryAgentSessionStore()
        session = AgentSession(session_id="conv_1")

        await store.save("conv_1", session)
        loaded = await store.load("conv_1")

        assert loaded is not None
        assert loaded.session_id == "conv_1"

    async def test_save_overwrites(self) -> None:
        store = InMemoryAgentSessionStore()
        await store.save("conv_1", AgentSession(session_id="conv_1"))
        await store.save("conv_1", AgentSession(session_id="conv_1_new"))

        loaded = await store.load("conv_1")
        assert loaded is not None
        assert loaded.session_id == "conv_1_new"

    async def test_sessions_are_isolated_per_id(self) -> None:
        store = InMemoryAgentSessionStore()
        await store.save("a", AgentSession(session_id="a"))
        await store.save("b", AgentSession(session_id="b"))

        assert (await store.load("a")).session_id == "a"  # type: ignore[union-attr]
        assert (await store.load("b")).session_id == "b"  # type: ignore[union-attr]


class TestFileAgentSessionStore:
    """JSON-on-disk store."""

    def test_creates_storage_dir_on_init(self, tmp_path: Path) -> None:
        storage = tmp_path / "does_not_exist_yet"
        assert not storage.exists()

        FileAgentSessionStore(storage_dir=storage)
        assert storage.is_dir()

    async def test_load_returns_none_when_file_missing(self, tmp_path: Path) -> None:
        store = FileAgentSessionStore(storage_dir=tmp_path)
        assert await store.load("missing") is None

    async def test_save_writes_json_file(self, tmp_path: Path) -> None:
        store = FileAgentSessionStore(storage_dir=tmp_path)
        session = AgentSession(session_id="conv_1")

        await store.save("conv_1", session)

        path = tmp_path / "conv_1.json"
        assert path.exists()
        # File content is valid JSON
        import json

        json.loads(path.read_text())

    async def test_save_then_load_roundtrip(self, tmp_path: Path) -> None:
        store = FileAgentSessionStore(storage_dir=tmp_path)
        session = AgentSession(session_id="conv_1")

        await store.save("conv_1", session)
        loaded = await store.load("conv_1")

        assert loaded is not None
        assert loaded.session_id == "conv_1"

    async def test_delete_removes_file(self, tmp_path: Path) -> None:
        store = FileAgentSessionStore(storage_dir=tmp_path)
        await store.save("conv_1", AgentSession(session_id="conv_1"))
        assert (tmp_path / "conv_1.json").exists()

        await store.delete("conv_1")
        assert not (tmp_path / "conv_1.json").exists()

    async def test_delete_missing_does_not_raise(self, tmp_path: Path) -> None:
        store = FileAgentSessionStore(storage_dir=tmp_path)
        # Should be a no-op, not an error.
        await store.delete("never_saved")


@pytest.mark.asyncio
async def test_in_memory_store_satisfies_protocol() -> None:
    """InMemory store implements the AgentSessionStore protocol surface."""
    from twilio_agent_connect_microsoft.agent_framework_types import AgentSessionStore

    store: AgentSessionStore = InMemoryAgentSessionStore()
    assert hasattr(store, "load")
    assert hasattr(store, "save")


@pytest.mark.asyncio
async def test_file_store_satisfies_protocol(tmp_path: Path) -> None:
    from twilio_agent_connect_microsoft.agent_framework_types import AgentSessionStore

    store: AgentSessionStore = FileAgentSessionStore(storage_dir=tmp_path)
    assert hasattr(store, "load")
    assert hasattr(store, "save")
