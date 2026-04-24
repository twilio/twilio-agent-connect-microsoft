"""Shared test fixtures."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def mock_tac() -> MagicMock:
    """Create a mock TAC instance."""
    tac = MagicMock()
    tac.on_message_ready = MagicMock()
    tac.on_conversation_ended = MagicMock()
    tac.on_interrupt = MagicMock()
    # Clients — tests that touch tools/memory will override these.
    tac.conversation_memory_client = MagicMock()
    tac.conversation_memory_client.retrieve_memory = AsyncMock()
    tac.knowledge_client = MagicMock()
    tac.config = MagicMock()
    tac.config.studio_handoff_flow_sid = "FW" + "0" * 32
    tac.config.phone_number = "+15555550100"
    tac.config.api_key = "SK" + "0" * 32
    tac.config.api_secret = "secret"
    return tac


@pytest.fixture
def mock_agent() -> MagicMock:
    """Create a mock Agent Framework Agent instance."""
    agent = MagicMock()

    # Non-streaming result has a .text attribute
    result = MagicMock()
    result.text = "Test response"
    agent.run = AsyncMock(return_value=result)

    return agent


@pytest.fixture
def mock_agent_factory(mock_agent: MagicMock) -> MagicMock:
    """Create a mock create_agent factory that returns a mock agent."""
    factory = MagicMock(return_value=mock_agent)
    return factory


@pytest.fixture
def mock_voice_session() -> MagicMock:
    """Create a mock ConversationSession for a voice call."""
    session = MagicMock()
    session.conversation_id = "conv_voice_123"
    session.channel = "voice"
    session.profile_id = "prof_123"
    session.author_info = MagicMock()
    session.author_info.address = "+15555550123"
    return session


@pytest.fixture
def mock_sms_session() -> MagicMock:
    """Create a mock ConversationSession for an SMS."""
    session = MagicMock()
    session.conversation_id = "conv_sms_456"
    session.channel = "sms"
    session.profile_id = "prof_123"
    session.author_info = MagicMock()
    session.author_info.address = "+15555550123"
    return session


@pytest.fixture
def mock_chat_session() -> MagicMock:
    """Create a mock ConversationSession for a chat."""
    session = MagicMock()
    session.conversation_id = "conv_chat_789"
    session.channel = "chat"
    session.profile_id = "prof_123"
    session.author_info = MagicMock()
    session.author_info.address = "user_123"
    return session


@pytest.fixture
def mock_memory_response() -> MagicMock:
    """Create a mock TACMemoryResponse."""
    memory = MagicMock()
    memory.observations = [MagicMock(text="User prefers Python")]
    memory.summaries = [MagicMock(text="Developer")]
    memory.model_dump = MagicMock(
        return_value={
            "profile_id": "prof_123",
            "observations": [{"text": "User prefers Python"}],
            "summaries": [{"text": "Developer"}],
            "sessions": [],
        }
    )
    return memory
