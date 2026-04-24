"""Tests for AgentFrameworkConnector."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from agent_framework import AgentSession

from tac_azure.agent_framework_connector import AgentFrameworkConnector
from tac_azure.stores.in_memory import InMemoryAgentSessionStore


# All connector construction patches the three channels so we don't reach
# into core TAC's network-attached setup logic.
def _patched_connector(**kwargs):
    """Build an AgentFrameworkConnector with Voice/SMS/Chat channels mocked."""
    return patch.multiple(
        "tac_azure.agent_framework_connector",
        VoiceChannel=MagicMock(return_value=MagicMock(send_response=AsyncMock())),
        SMSChannel=MagicMock(return_value=MagicMock(send_response=AsyncMock())),
        ChatChannel=MagicMock(return_value=MagicMock(send_response=AsyncMock())),
    )


class TestAgentFrameworkConnectorInit:
    """Connector construction and callback wiring."""

    def test_initialization_registers_tac_callbacks(
        self, mock_tac: MagicMock, mock_agent_factory: MagicMock
    ) -> None:
        with _patched_connector():
            AgentFrameworkConnector(tac=mock_tac, create_agent=mock_agent_factory)

        mock_tac.on_message_ready.assert_called_once()
        mock_tac.on_conversation_ended.assert_called_once()
        mock_tac.on_interrupt.assert_called_once()

    def test_exposes_three_channel_instances(
        self, mock_tac: MagicMock, mock_agent_factory: MagicMock
    ) -> None:
        with _patched_connector():
            connector = AgentFrameworkConnector(tac=mock_tac, create_agent=mock_agent_factory)

        assert connector.voice_channel is not None
        assert connector.sms_channel is not None
        assert connector.chat_channel is not None

    def test_defaults_to_in_memory_session_store(
        self, mock_tac: MagicMock, mock_agent_factory: MagicMock
    ) -> None:
        with _patched_connector():
            connector = AgentFrameworkConnector(tac=mock_tac, create_agent=mock_agent_factory)

        assert isinstance(connector.session_store, InMemoryAgentSessionStore)

    def test_accepts_custom_session_store(
        self, mock_tac: MagicMock, mock_agent_factory: MagicMock
    ) -> None:
        custom = InMemoryAgentSessionStore()

        with _patched_connector():
            connector = AgentFrameworkConnector(
                tac=mock_tac, create_agent=mock_agent_factory, session_store=custom
            )

        assert connector.session_store is custom

    def test_voice_session_manager_injected(
        self, mock_tac: MagicMock, mock_agent_factory: MagicMock
    ) -> None:
        """ThreadSafeSessionManager is merged into VoiceChannelConfig so the
        voice channel can cancel in-flight streams on interrupt."""
        with _patched_connector():
            connector = AgentFrameworkConnector(tac=mock_tac, create_agent=mock_agent_factory)

        assert connector._session_manager is not None


class TestMessageDispatch:
    """Unified _handle_message dispatches on context.channel."""

    async def test_voice_channel_routes_to_voice_handler(
        self,
        mock_tac: MagicMock,
        mock_agent_factory: MagicMock,
        mock_voice_session: MagicMock,
    ) -> None:
        with _patched_connector():
            connector = AgentFrameworkConnector(tac=mock_tac, create_agent=mock_agent_factory)

        connector._handle_voice_message = AsyncMock()
        connector._handle_messaging_message = AsyncMock()

        await connector._handle_message("hi", mock_voice_session, None)

        connector._handle_voice_message.assert_awaited_once()
        connector._handle_messaging_message.assert_not_awaited()

    async def test_sms_channel_routes_to_messaging_handler(
        self,
        mock_tac: MagicMock,
        mock_agent_factory: MagicMock,
        mock_sms_session: MagicMock,
    ) -> None:
        with _patched_connector():
            connector = AgentFrameworkConnector(tac=mock_tac, create_agent=mock_agent_factory)

        connector._handle_voice_message = AsyncMock()
        connector._handle_messaging_message = AsyncMock()

        await connector._handle_message("hi", mock_sms_session, None)

        connector._handle_messaging_message.assert_awaited_once()
        connector._handle_voice_message.assert_not_awaited()

    async def test_chat_channel_routes_to_messaging_handler(
        self,
        mock_tac: MagicMock,
        mock_agent_factory: MagicMock,
        mock_chat_session: MagicMock,
    ) -> None:
        with _patched_connector():
            connector = AgentFrameworkConnector(tac=mock_tac, create_agent=mock_agent_factory)

        connector._handle_voice_message = AsyncMock()
        connector._handle_messaging_message = AsyncMock()

        await connector._handle_message("hi", mock_chat_session, None)

        connector._handle_messaging_message.assert_awaited_once()

    async def test_unknown_channel_logged_not_dispatched(
        self,
        mock_tac: MagicMock,
        mock_agent_factory: MagicMock,
    ) -> None:
        with _patched_connector():
            connector = AgentFrameworkConnector(tac=mock_tac, create_agent=mock_agent_factory)

        connector._handle_voice_message = AsyncMock()
        connector._handle_messaging_message = AsyncMock()

        unknown = MagicMock()
        unknown.channel = "whatsapp"
        unknown.conversation_id = "conv_x"

        await connector._handle_message("hi", unknown, None)

        connector._handle_voice_message.assert_not_awaited()
        connector._handle_messaging_message.assert_not_awaited()


class TestMessagingChannelSelection:
    """_get_messaging_channel picks the right channel by name."""

    def test_sms_returns_sms_channel(
        self, mock_tac: MagicMock, mock_agent_factory: MagicMock
    ) -> None:
        with _patched_connector():
            connector = AgentFrameworkConnector(tac=mock_tac, create_agent=mock_agent_factory)

        assert connector._get_messaging_channel("sms") is connector.sms_channel

    def test_chat_returns_chat_channel(
        self, mock_tac: MagicMock, mock_agent_factory: MagicMock
    ) -> None:
        with _patched_connector():
            connector = AgentFrameworkConnector(tac=mock_tac, create_agent=mock_agent_factory)

        assert connector._get_messaging_channel("chat") is connector.chat_channel

    def test_unknown_raises(
        self, mock_tac: MagicMock, mock_agent_factory: MagicMock
    ) -> None:
        with _patched_connector():
            connector = AgentFrameworkConnector(tac=mock_tac, create_agent=mock_agent_factory)

        with pytest.raises(ValueError, match="Unsupported messaging channel"):
            connector._get_messaging_channel("whatsapp")


class TestMessagingMessageHandler:
    """SMS/chat share one handler: load session → run agent → save session."""

    async def test_loads_existing_session_and_calls_agent(
        self,
        mock_tac: MagicMock,
        mock_agent_factory: MagicMock,
        mock_agent: MagicMock,
        mock_sms_session: MagicMock,
    ) -> None:
        with _patched_connector():
            connector = AgentFrameworkConnector(tac=mock_tac, create_agent=mock_agent_factory)

        # Pre-seed the session store.
        existing = AgentSession(session_id="conv_sms_456")
        await connector.session_store.save("conv_sms_456", existing)

        await connector._handle_messaging_message("hello", mock_sms_session, None)

        mock_agent_factory.assert_called_once_with(mock_sms_session)
        mock_agent.run.assert_awaited_once()
        _, kwargs = mock_agent.run.await_args
        assert kwargs["session"] is existing

    async def test_creates_new_session_when_missing(
        self,
        mock_tac: MagicMock,
        mock_agent_factory: MagicMock,
        mock_agent: MagicMock,
        mock_sms_session: MagicMock,
    ) -> None:
        with _patched_connector():
            connector = AgentFrameworkConnector(tac=mock_tac, create_agent=mock_agent_factory)

        await connector._handle_messaging_message("hello", mock_sms_session, None)

        # A fresh session was passed (not None), scoped to the conversation id.
        _, kwargs = mock_agent.run.await_args
        assert kwargs["session"].session_id == "conv_sms_456"

    async def test_sends_response_via_sms_channel(
        self,
        mock_tac: MagicMock,
        mock_agent_factory: MagicMock,
        mock_sms_session: MagicMock,
    ) -> None:
        with _patched_connector():
            connector = AgentFrameworkConnector(tac=mock_tac, create_agent=mock_agent_factory)

        await connector._handle_messaging_message("hello", mock_sms_session, None)

        connector.sms_channel.send_response.assert_awaited_once_with(
            "conv_sms_456", "Test response", role="assistant"
        )
        connector.chat_channel.send_response.assert_not_awaited()

    async def test_sends_response_via_chat_channel(
        self,
        mock_tac: MagicMock,
        mock_agent_factory: MagicMock,
        mock_chat_session: MagicMock,
    ) -> None:
        with _patched_connector():
            connector = AgentFrameworkConnector(tac=mock_tac, create_agent=mock_agent_factory)

        await connector._handle_messaging_message("hello", mock_chat_session, None)

        connector.chat_channel.send_response.assert_awaited_once_with(
            "conv_chat_789", "Test response", role="assistant"
        )
        connector.sms_channel.send_response.assert_not_awaited()

    async def test_persists_session_after_run(
        self,
        mock_tac: MagicMock,
        mock_agent_factory: MagicMock,
        mock_sms_session: MagicMock,
    ) -> None:
        with _patched_connector():
            connector = AgentFrameworkConnector(tac=mock_tac, create_agent=mock_agent_factory)
        connector.session_store = MagicMock(load=AsyncMock(return_value=None), save=AsyncMock())

        await connector._handle_messaging_message("hello", mock_sms_session, None)

        connector.session_store.save.assert_awaited_once()

    async def test_error_sends_fallback_response_and_still_saves(
        self,
        mock_tac: MagicMock,
        mock_agent_factory: MagicMock,
        mock_agent: MagicMock,
        mock_sms_session: MagicMock,
    ) -> None:
        mock_agent.run.side_effect = RuntimeError("boom")

        with _patched_connector():
            connector = AgentFrameworkConnector(tac=mock_tac, create_agent=mock_agent_factory)
        connector.session_store = MagicMock(load=AsyncMock(return_value=None), save=AsyncMock())

        await connector._handle_messaging_message("hello", mock_sms_session, None)

        # Fallback error response was sent.
        connector.sms_channel.send_response.assert_awaited_once()
        # Session still persisted (may contain new Foundry thread id).
        connector.session_store.save.assert_awaited_once()


class TestOnMessageHook:
    """on_message replaces the default memory-context formatting."""

    def test_custom_on_message_is_used(
        self,
        mock_tac: MagicMock,
        mock_agent_factory: MagicMock,
        mock_sms_session: MagicMock,
    ) -> None:
        on_message = MagicMock(return_value="decorated: hello")

        with _patched_connector():
            connector = AgentFrameworkConnector(
                tac=mock_tac, create_agent=mock_agent_factory, on_message=on_message
            )

        result = connector._build_message("hello", mock_sms_session, None)

        on_message.assert_called_once_with("hello", mock_sms_session, None)
        assert result == "decorated: hello"

    def test_default_formats_memory_context(
        self,
        mock_tac: MagicMock,
        mock_agent_factory: MagicMock,
        mock_sms_session: MagicMock,
        mock_memory_response: MagicMock,
    ) -> None:
        with _patched_connector():
            connector = AgentFrameworkConnector(tac=mock_tac, create_agent=mock_agent_factory)

        with patch(
            "tac_azure.agent_framework_connector.format_memory_context",
            return_value="formatted",
        ) as fmt:
            result = connector._build_message("hello", mock_sms_session, mock_memory_response)

        fmt.assert_called_once_with(mock_memory_response, "hello")
        assert result == "formatted"


class TestOnErrorHook:
    """on_error lets callers customize fallback response wording."""

    def test_custom_on_error_response(
        self,
        mock_tac: MagicMock,
        mock_agent_factory: MagicMock,
        mock_sms_session: MagicMock,
    ) -> None:
        on_error = MagicMock(return_value="custom oops")

        with _patched_connector():
            connector = AgentFrameworkConnector(
                tac=mock_tac, create_agent=mock_agent_factory, on_error=on_error
            )

        result = connector._get_error_response(RuntimeError("x"), mock_sms_session)

        assert result == "custom oops"

    def test_on_error_failure_falls_back_to_default(
        self,
        mock_tac: MagicMock,
        mock_agent_factory: MagicMock,
        mock_sms_session: MagicMock,
    ) -> None:
        on_error = MagicMock(side_effect=RuntimeError("hook broke"))

        with _patched_connector():
            connector = AgentFrameworkConnector(
                tac=mock_tac, create_agent=mock_agent_factory, on_error=on_error
            )

        result = connector._get_error_response(RuntimeError("x"), mock_sms_session)

        # Should still return a non-empty fallback rather than raise.
        assert isinstance(result, str)
        assert result

    def test_default_returns_string(
        self,
        mock_tac: MagicMock,
        mock_agent_factory: MagicMock,
        mock_sms_session: MagicMock,
    ) -> None:
        with _patched_connector():
            connector = AgentFrameworkConnector(tac=mock_tac, create_agent=mock_agent_factory)

        result = connector._get_error_response(RuntimeError("x"), mock_sms_session)

        assert isinstance(result, str)
        assert result


class TestVoiceAgentCaching:
    """Voice agent + AgentSession are cached per-conversation for the call."""

    def test_agent_cached_per_conversation(
        self,
        mock_tac: MagicMock,
        mock_agent_factory: MagicMock,
        mock_voice_session: MagicMock,
    ) -> None:
        with _patched_connector():
            connector = AgentFrameworkConnector(tac=mock_tac, create_agent=mock_agent_factory)

        a1 = connector._get_or_create_voice_agent("conv_voice_123", mock_voice_session)
        a2 = connector._get_or_create_voice_agent("conv_voice_123", mock_voice_session)

        assert a1 is a2
        mock_agent_factory.assert_called_once()

    def test_different_conversations_get_different_agents(
        self,
        mock_tac: MagicMock,
        mock_agent_factory: MagicMock,
        mock_voice_session: MagicMock,
    ) -> None:
        with _patched_connector():
            connector = AgentFrameworkConnector(tac=mock_tac, create_agent=mock_agent_factory)

        connector._get_or_create_voice_agent("conv_a", mock_voice_session)
        connector._get_or_create_voice_agent("conv_b", mock_voice_session)

        assert mock_agent_factory.call_count == 2

    def test_voice_session_cached_per_conversation(
        self, mock_tac: MagicMock, mock_agent_factory: MagicMock
    ) -> None:
        with _patched_connector():
            connector = AgentFrameworkConnector(tac=mock_tac, create_agent=mock_agent_factory)

        s1 = connector._get_or_create_voice_session("conv_voice_123")
        s2 = connector._get_or_create_voice_session("conv_voice_123")

        assert s1 is s2
        assert s1.session_id == "conv_voice_123"


class TestVoiceCleanup:
    """Conversation ended → voice agent and session are dropped from caches."""

    async def test_conversation_ended_cleans_up_voice(
        self,
        mock_tac: MagicMock,
        mock_agent_factory: MagicMock,
        mock_voice_session: MagicMock,
    ) -> None:
        with _patched_connector():
            connector = AgentFrameworkConnector(tac=mock_tac, create_agent=mock_agent_factory)

        connector._get_or_create_voice_agent("conv_voice_123", mock_voice_session)
        connector._get_or_create_voice_session("conv_voice_123")

        # Background save is fire-and-forget; stub the store to avoid touching it.
        connector.session_store = MagicMock(save=AsyncMock())

        await connector._handle_conversation_ended(mock_voice_session)

        assert "conv_voice_123" not in connector._voice_agents
        assert "conv_voice_123" not in connector._voice_sessions

    async def test_conversation_ended_for_sms_is_noop(
        self,
        mock_tac: MagicMock,
        mock_agent_factory: MagicMock,
        mock_sms_session: MagicMock,
    ) -> None:
        with _patched_connector():
            connector = AgentFrameworkConnector(tac=mock_tac, create_agent=mock_agent_factory)

        # Should not raise even though there's no voice agent for this SMS.
        await connector._handle_conversation_ended(mock_sms_session)
