"""Tests for VoiceLiveConnector.

The connector is a thin coordinator over ``VoiceLiveSession`` (which owns
the WebSocket).  These tests mock the session entirely so no network or
WebSocket library code is exercised.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tac_microsoft.voice_live_connector import VoiceLiveConnector
from tac_microsoft.voice_live_types import VoiceLiveConfig


@pytest.fixture
def voice_live_config() -> VoiceLiveConfig:
    return VoiceLiveConfig(
        endpoint="test.services.ai.azure.com",
        model="gpt-4o",
        api_key="test-key",
        instructions="You are helpful.",
    )


def _patched_connector():
    """Build a VoiceLiveConnector with VoiceChannel mocked."""
    return patch(
        "tac_microsoft.voice_live_connector.VoiceChannel",
        MagicMock(return_value=MagicMock(send_response=AsyncMock())),
    )


def _mock_voice_session(chunks: list[str] | None = None) -> MagicMock:
    """Build a mock VoiceLiveSession with async lifecycle methods."""
    session = MagicMock()
    session.connect = AsyncMock()
    session.configure = AsyncMock()
    session.close = AsyncMock()
    session.cancel_response = AsyncMock()

    async def _stream(_msg: str):
        for chunk in chunks or ["Test ", "response"]:
            yield chunk

    session.send_message_and_stream = _stream
    return session


class TestVoiceLiveConnectorInit:
    """Connector construction and callback wiring."""

    def test_initialization_registers_tac_callbacks(
        self, mock_tac: MagicMock, voice_live_config: VoiceLiveConfig
    ) -> None:
        with _patched_connector():
            VoiceLiveConnector(tac=mock_tac, config=voice_live_config)

        mock_tac.on_message_ready.assert_called_once()
        mock_tac.on_conversation_ended.assert_called_once()
        mock_tac.on_interrupt.assert_called_once()

    def test_exposes_voice_channel(
        self, mock_tac: MagicMock, voice_live_config: VoiceLiveConfig
    ) -> None:
        with _patched_connector():
            connector = VoiceLiveConnector(tac=mock_tac, config=voice_live_config)

        assert connector.voice_channel is not None

    def test_starts_with_empty_session_cache(
        self, mock_tac: MagicMock, voice_live_config: VoiceLiveConfig
    ) -> None:
        with _patched_connector():
            connector = VoiceLiveConnector(tac=mock_tac, config=voice_live_config)

        assert connector._voice_sessions == {}

    def test_voice_session_manager_injected(
        self, mock_tac: MagicMock, voice_live_config: VoiceLiveConfig
    ) -> None:
        """ThreadSafeSessionManager is merged into VoiceChannelConfig so the
        voice channel can cancel in-flight streams on interrupt."""
        with _patched_connector():
            connector = VoiceLiveConnector(tac=mock_tac, config=voice_live_config)

        assert connector._session_manager is not None


class TestMessageDispatch:
    """_handle_message only handles voice; everything else is ignored."""

    async def test_voice_channel_routes_to_voice_handler(
        self,
        mock_tac: MagicMock,
        voice_live_config: VoiceLiveConfig,
        mock_voice_session: MagicMock,
    ) -> None:
        with _patched_connector():
            connector = VoiceLiveConnector(tac=mock_tac, config=voice_live_config)

        connector._handle_voice_message = AsyncMock()

        await connector._handle_message("hi", mock_voice_session, None)

        connector._handle_voice_message.assert_awaited_once()

    async def test_non_voice_channel_is_ignored(
        self,
        mock_tac: MagicMock,
        voice_live_config: VoiceLiveConfig,
        mock_sms_session: MagicMock,
    ) -> None:
        with _patched_connector():
            connector = VoiceLiveConnector(tac=mock_tac, config=voice_live_config)

        connector._handle_voice_message = AsyncMock()

        await connector._handle_message("hi", mock_sms_session, None)

        connector._handle_voice_message.assert_not_awaited()


class TestSessionLifecycle:
    """Session is created lazily, reused within a call, and closed on end."""

    async def test_session_created_and_configured_on_first_use(
        self, mock_tac: MagicMock, voice_live_config: VoiceLiveConfig
    ) -> None:
        session = _mock_voice_session()

        with (
            _patched_connector(),
            patch(
                "tac_microsoft.voice_live_connector.VoiceLiveSession",
                return_value=session,
            ),
        ):
            connector = VoiceLiveConnector(tac=mock_tac, config=voice_live_config)
            result = await connector._get_or_create_voice_session("conv_1")

        assert result is session
        session.connect.assert_awaited_once()
        session.configure.assert_awaited_once()

    async def test_session_reused_within_same_conversation(
        self, mock_tac: MagicMock, voice_live_config: VoiceLiveConfig
    ) -> None:
        session = _mock_voice_session()

        with (
            _patched_connector(),
            patch(
                "tac_microsoft.voice_live_connector.VoiceLiveSession",
                return_value=session,
            ) as session_cls,
        ):
            connector = VoiceLiveConnector(tac=mock_tac, config=voice_live_config)

            s1 = await connector._get_or_create_voice_session("conv_1")
            s2 = await connector._get_or_create_voice_session("conv_1")

        assert s1 is s2
        session_cls.assert_called_once()
        session.connect.assert_awaited_once()

    async def test_separate_conversations_get_separate_sessions(
        self, mock_tac: MagicMock, voice_live_config: VoiceLiveConfig
    ) -> None:
        sessions = [_mock_voice_session(), _mock_voice_session()]

        with (
            _patched_connector(),
            patch(
                "tac_microsoft.voice_live_connector.VoiceLiveSession",
                side_effect=sessions,
            ),
        ):
            connector = VoiceLiveConnector(tac=mock_tac, config=voice_live_config)

            s1 = await connector._get_or_create_voice_session("conv_a")
            s2 = await connector._get_or_create_voice_session("conv_b")

        assert s1 is not s2

    async def test_conversation_ended_closes_and_removes_session(
        self,
        mock_tac: MagicMock,
        voice_live_config: VoiceLiveConfig,
        mock_voice_session: MagicMock,
    ) -> None:
        session = _mock_voice_session()

        with (
            _patched_connector(),
            patch(
                "tac_microsoft.voice_live_connector.VoiceLiveSession",
                return_value=session,
            ),
        ):
            connector = VoiceLiveConnector(tac=mock_tac, config=voice_live_config)
            await connector._get_or_create_voice_session("conv_voice_123")

            await connector._handle_conversation_ended(mock_voice_session)

        session.close.assert_awaited_once()
        assert "conv_voice_123" not in connector._voice_sessions

    async def test_conversation_ended_without_session_is_noop(
        self,
        mock_tac: MagicMock,
        voice_live_config: VoiceLiveConfig,
        mock_voice_session: MagicMock,
    ) -> None:
        with _patched_connector():
            connector = VoiceLiveConnector(tac=mock_tac, config=voice_live_config)

        # No session was ever created — should not raise.
        await connector._handle_conversation_ended(mock_voice_session)

    async def test_conversation_ended_ignores_non_voice_channel(
        self,
        mock_tac: MagicMock,
        voice_live_config: VoiceLiveConfig,
        mock_sms_session: MagicMock,
    ) -> None:
        with _patched_connector():
            connector = VoiceLiveConnector(tac=mock_tac, config=voice_live_config)

        # Even if an SMS session somehow ended up routed here, don't try to
        # close a voice session for it.
        await connector._handle_conversation_ended(mock_sms_session)


class TestInterrupt:
    """Interrupt cancels the in-flight Voice Live response."""

    async def test_interrupt_cancels_active_session(
        self,
        mock_tac: MagicMock,
        voice_live_config: VoiceLiveConfig,
        mock_voice_session: MagicMock,
    ) -> None:
        session = _mock_voice_session()

        with (
            _patched_connector(),
            patch(
                "tac_microsoft.voice_live_connector.VoiceLiveSession",
                return_value=session,
            ),
        ):
            connector = VoiceLiveConnector(tac=mock_tac, config=voice_live_config)
            await connector._get_or_create_voice_session("conv_voice_123")

            await connector._handle_interrupt(mock_voice_session, {})

        session.cancel_response.assert_awaited_once()

    async def test_interrupt_without_session_is_noop(
        self,
        mock_tac: MagicMock,
        voice_live_config: VoiceLiveConfig,
        mock_voice_session: MagicMock,
    ) -> None:
        with _patched_connector():
            connector = VoiceLiveConnector(tac=mock_tac, config=voice_live_config)

        # Interrupt arriving before a session exists should log, not raise.
        await connector._handle_interrupt(mock_voice_session, {})


class TestStreaming:
    """_stream_response yields chunks from the session and handles errors."""

    async def test_stream_response_yields_session_chunks(
        self,
        mock_tac: MagicMock,
        voice_live_config: VoiceLiveConfig,
        mock_voice_session: MagicMock,
    ) -> None:
        session = _mock_voice_session(chunks=["alpha ", "beta ", "gamma"])

        with (
            _patched_connector(),
            patch(
                "tac_microsoft.voice_live_connector.VoiceLiveSession",
                return_value=session,
            ),
        ):
            connector = VoiceLiveConnector(tac=mock_tac, config=voice_live_config)

            chunks = [
                chunk
                async for chunk in connector._stream_response("hello", mock_voice_session, None)
            ]

        assert chunks == ["alpha ", "beta ", "gamma"]

    async def test_stream_response_session_error_yields_fallback(
        self,
        mock_tac: MagicMock,
        voice_live_config: VoiceLiveConfig,
        mock_voice_session: MagicMock,
    ) -> None:
        session = _mock_voice_session()

        async def _boom(_msg: str):
            raise RuntimeError("stream died")
            yield  # pragma: no cover — make this an async generator

        session.send_message_and_stream = _boom

        with (
            _patched_connector(),
            patch(
                "tac_microsoft.voice_live_connector.VoiceLiveSession",
                return_value=session,
            ),
        ):
            connector = VoiceLiveConnector(tac=mock_tac, config=voice_live_config)

            chunks = [
                chunk
                async for chunk in connector._stream_response("hello", mock_voice_session, None)
            ]

        # Default fallback response wording, and session was cleaned up.
        assert len(chunks) == 1
        assert isinstance(chunks[0], str) and chunks[0]
        assert "conv_voice_123" not in connector._voice_sessions
        session.close.assert_awaited_once()

    async def test_handle_voice_message_sends_stream_to_channel(
        self,
        mock_tac: MagicMock,
        voice_live_config: VoiceLiveConfig,
        mock_voice_session: MagicMock,
    ) -> None:
        session = _mock_voice_session()

        with (
            _patched_connector(),
            patch(
                "tac_microsoft.voice_live_connector.VoiceLiveSession",
                return_value=session,
            ),
        ):
            connector = VoiceLiveConnector(tac=mock_tac, config=voice_live_config)

            await connector._handle_voice_message("hello", mock_voice_session, None)

        # The channel was called with the conversation id and a generator.
        connector.voice_channel.send_response.assert_awaited_once()
        args, _ = connector.voice_channel.send_response.await_args
        assert args[0] == "conv_voice_123"


class TestOnMessageHook:
    """on_message replaces the default memory-context formatting."""

    def test_custom_on_message_is_used(
        self,
        mock_tac: MagicMock,
        voice_live_config: VoiceLiveConfig,
        mock_voice_session: MagicMock,
    ) -> None:
        on_message = MagicMock(return_value="decorated: hello")

        with _patched_connector():
            connector = VoiceLiveConnector(
                tac=mock_tac, config=voice_live_config, on_message=on_message
            )

        result = connector._build_message("hello", mock_voice_session, None)

        on_message.assert_called_once_with("hello", mock_voice_session, None)
        assert result == "decorated: hello"

    def test_default_formats_memory_context(
        self,
        mock_tac: MagicMock,
        voice_live_config: VoiceLiveConfig,
        mock_voice_session: MagicMock,
        mock_memory_response: MagicMock,
    ) -> None:
        with _patched_connector():
            connector = VoiceLiveConnector(tac=mock_tac, config=voice_live_config)

        with patch(
            "tac_microsoft.voice_live_connector.format_memory_context",
            return_value="formatted",
        ) as fmt:
            result = connector._build_message("hello", mock_voice_session, mock_memory_response)

        fmt.assert_called_once_with(mock_memory_response, "hello")
        assert result == "formatted"


class TestOnErrorHook:
    """on_error lets callers customize fallback wording."""

    def test_custom_on_error_response(
        self,
        mock_tac: MagicMock,
        voice_live_config: VoiceLiveConfig,
        mock_voice_session: MagicMock,
    ) -> None:
        on_error = MagicMock(return_value="custom oops")

        with _patched_connector():
            connector = VoiceLiveConnector(
                tac=mock_tac, config=voice_live_config, on_error=on_error
            )

        result = connector._get_error_response(RuntimeError("x"), mock_voice_session)

        assert result == "custom oops"

    def test_on_error_failure_falls_back_to_default(
        self,
        mock_tac: MagicMock,
        voice_live_config: VoiceLiveConfig,
        mock_voice_session: MagicMock,
    ) -> None:
        on_error = MagicMock(side_effect=RuntimeError("hook broke"))

        with _patched_connector():
            connector = VoiceLiveConnector(
                tac=mock_tac, config=voice_live_config, on_error=on_error
            )

        result = connector._get_error_response(RuntimeError("x"), mock_voice_session)

        # Should still return a non-empty fallback rather than raise.
        assert isinstance(result, str)
        assert result

    def test_default_returns_string(
        self,
        mock_tac: MagicMock,
        voice_live_config: VoiceLiveConfig,
        mock_voice_session: MagicMock,
    ) -> None:
        with _patched_connector():
            connector = VoiceLiveConnector(tac=mock_tac, config=voice_live_config)

        result = connector._get_error_response(RuntimeError("x"), mock_voice_session)

        assert isinstance(result, str)
        assert result
