"""Tests for TACHostedAgentsApp.

These tests exercise the dispatch logic without booting a real
``InvocationAgentServerHost`` — we patch the lazy host import so the
class can be constructed in environments where the vendored wheel isn't
installed.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from tac.channels.messaging import MessagingChannel
from tac.channels.voice import VoiceChannel
from tac.models.voice import TwiMLOptions

from tac_microsoft.hosted_agents_server import (
    StarletteWebSocketAdapter,
    TACHostedAgentsApp,
    _IdempotencyCache,
)


# A stand-in for InvocationAgentServerHost that records decorator calls
# so tests can introspect what handlers got registered. We patch the
# import in hosted_agents_server.py rather than installing the real one
# (it boots a Starlette ASGI app that we don't need for unit tests).
class _FakeInvocationHost:
    def __init__(self) -> None:
        self.invoke_handler_func: Any = None
        self.ws_handler_func: Any = None
        self.run_called = False

    def invoke_handler(self, func: Any) -> Any:
        self.invoke_handler_func = func
        return func

    def ws_handler(self, func: Any) -> Any:
        self.ws_handler_func = func
        return func

    def run(self) -> None:
        self.run_called = True


def _make_tac(public_domain: str = "test.example.com/twilio") -> MagicMock:
    """Mock TAC whose config carries the 2.x voice URL fields.

    In TAC 2.x these live on TACConfig (not TACServerConfig), and the hosted
    agents server reads them from ``tac.config``.
    """
    tac = MagicMock()
    tac.config.voice_public_domain = public_domain
    tac.config.voice_websocket_path = "/ws"
    tac.config.voice_action_path = "/conversation-relay-callback"
    return tac


def _build_server(
    *,
    voice_channel: MagicMock | None = None,
    messaging_channels: list[MagicMock] | None = None,
    public_domain: str = "test.example.com/twilio",
) -> tuple[TACHostedAgentsApp, _FakeInvocationHost]:
    fake_host = _FakeInvocationHost()
    with patch(
        "tac_microsoft.hosted_agents_server.InvocationAgentServerHost",
        return_value=fake_host,
    ):
        server = TACHostedAgentsApp(
            tac=_make_tac(public_domain),
            voice_channel=voice_channel,
            messaging_channels=messaging_channels or [],
        )
    return server, fake_host


def _make_request(
    body: Any,
    *,
    session_id: str | None = None,
    idempotency_token: str | None = None,
) -> MagicMock:
    request = MagicMock()
    request.state.session_id = session_id
    request.json = AsyncMock(return_value=body)
    headers = {}
    if idempotency_token is not None:
        headers["i-twilio-idempotency-token"] = idempotency_token
    request.headers = headers
    return request


def _make_voice_channel() -> MagicMock:
    # spec= so the server's isinstance(voice_channel, VoiceChannel) check passes.
    channel = MagicMock(spec=VoiceChannel)
    channel.handle_incoming_call = AsyncMock(return_value="<Response/>")
    channel.handle_websocket = AsyncMock()
    channel.process_webhook = AsyncMock()
    channel.get_channel_name = MagicMock(return_value="voice")
    return channel


def _make_messaging_channel(name: str = "sms") -> MagicMock:
    # spec= so the server's isinstance(c, MessagingChannel) check passes.
    channel = MagicMock(spec=MessagingChannel)
    channel.process_webhook = AsyncMock()
    channel.get_channel_name = MagicMock(return_value=name)
    return channel


# ---------------------------------------------------------------------------
# Construction / handler registration
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_registers_invoke_handler_when_messaging_only(self) -> None:
        sms = _make_messaging_channel()
        _, host = _build_server(messaging_channels=[sms])
        assert host.invoke_handler_func is not None
        assert host.ws_handler_func is None  # no voice channel → no WS handler

    def test_registers_ws_handler_when_voice_present(self) -> None:
        voice = _make_voice_channel()
        _, host = _build_server(voice_channel=voice)
        assert host.invoke_handler_func is not None
        assert host.ws_handler_func is not None

    def test_voice_channel_added_to_webhook_fanout(self) -> None:
        voice = _make_voice_channel()
        sms = _make_messaging_channel()
        server, _ = _build_server(voice_channel=voice, messaging_channels=[sms])
        assert voice in server._webhook_channels
        assert sms in server._webhook_channels

    def test_start_calls_app_run(self) -> None:
        server, host = _build_server(messaging_channels=[_make_messaging_channel()])
        server.start()
        assert host.run_called is True

    def test_none_in_messaging_channels_raises_typeerror(self) -> None:
        """A None slipping into messaging_channels (e.g. an unconfigured
        connector.rcs_channel) is rejected at construction with a clear error,
        not an opaque AttributeError during webhook dispatch."""
        with pytest.raises(TypeError, match="MessagingChannel"):
            _build_server(messaging_channels=[_make_messaging_channel(), None])

    def test_wrong_type_in_messaging_channels_raises_typeerror(self) -> None:
        with pytest.raises(TypeError, match="MessagingChannel"):
            _build_server(messaging_channels=["not a channel"])

    def test_non_voice_channel_raises_typeerror(self) -> None:
        with pytest.raises(TypeError, match="VoiceChannel"):
            _build_server(voice_channel=_make_messaging_channel())


# ---------------------------------------------------------------------------
# CO webhook dispatch
# ---------------------------------------------------------------------------


CO_PAYLOAD = {
    "eventType": "COMMUNICATION_CREATED",
    "data": {"conversationId": "conv_abc", "id": "comm_123"},
}


class TestCoWebhookDispatch:
    @pytest.mark.asyncio
    async def test_forwards_valid_co_payload_to_messaging_channel(self) -> None:
        sms = _make_messaging_channel()
        server, _ = _build_server(messaging_channels=[sms])

        request = _make_request(CO_PAYLOAD, session_id="conv_abc", idempotency_token="t1")
        response = await server._dispatch_invoke(request)

        assert response.status_code == 200
        sms.process_webhook.assert_awaited_once_with(CO_PAYLOAD, "t1")

    @pytest.mark.asyncio
    async def test_fans_out_to_all_messaging_channels(self) -> None:
        sms = _make_messaging_channel("sms")
        whatsapp = _make_messaging_channel("whatsapp")
        server, _ = _build_server(messaging_channels=[sms, whatsapp])

        request = _make_request(CO_PAYLOAD, session_id="conv_abc")
        await server._dispatch_invoke(request)

        sms.process_webhook.assert_awaited_once()
        whatsapp.process_webhook.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_includes_voice_channel_in_fanout(self) -> None:
        # Mirrors TACFastAPIServer behavior: voice channel receives webhook
        # events too (e.g. CONVERSATION_UPDATED for call cleanup).
        voice = _make_voice_channel()
        sms = _make_messaging_channel()
        server, _ = _build_server(voice_channel=voice, messaging_channels=[sms])

        request = _make_request(CO_PAYLOAD, session_id="conv_abc")
        await server._dispatch_invoke(request)

        voice.process_webhook.assert_awaited_once()
        sms.process_webhook.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_rejects_non_co_payload(self) -> None:
        sms = _make_messaging_channel()
        server, _ = _build_server(messaging_channels=[sms])

        request = _make_request({"hello": "world"})
        response = await server._dispatch_invoke(request)

        assert response.status_code == 400
        sms.process_webhook.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_rejects_session_id_conversation_id_mismatch(self) -> None:
        sms = _make_messaging_channel()
        server, _ = _build_server(messaging_channels=[sms])

        request = _make_request(CO_PAYLOAD, session_id="conv_WRONG")
        response = await server._dispatch_invoke(request)

        assert response.status_code == 400
        sms.process_webhook.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_matches_conversation_updated_via_data_id(self) -> None:
        # CONVERSATION_UPDATED uses ``data.id`` instead of ``data.conversationId``.
        sms = _make_messaging_channel()
        server, _ = _build_server(messaging_channels=[sms])

        body = {"eventType": "CONVERSATION_UPDATED", "data": {"id": "conv_xyz"}}
        request = _make_request(body, session_id="conv_xyz")
        response = await server._dispatch_invoke(request)

        assert response.status_code == 200
        sms.process_webhook.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_accepts_conversation_created_as_noop(self) -> None:
        # CONVERSATION_CREATED is the first event CO fires for a new
        # conversation. It must be accepted (200) and forwarded — not
        # rejected with a 400 — even though channels treat it as a no-op.
        sms = _make_messaging_channel()
        server, _ = _build_server(messaging_channels=[sms])

        body = {"eventType": "CONVERSATION_CREATED", "data": {"id": "conv_new"}}
        request = _make_request(body, session_id="conv_new")
        response = await server._dispatch_invoke(request)

        assert response.status_code == 200
        sms.process_webhook.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_dedups_by_idempotency_token(self) -> None:
        sms = _make_messaging_channel()
        server, _ = _build_server(messaging_channels=[sms])

        first = _make_request(CO_PAYLOAD, session_id="conv_abc", idempotency_token="dup")
        second = _make_request(CO_PAYLOAD, session_id="conv_abc", idempotency_token="dup")

        assert (await server._dispatch_invoke(first)).status_code == 200
        second_resp = await server._dispatch_invoke(second)
        assert second_resp.status_code == 200
        assert b"duplicate" in second_resp.body
        sms.process_webhook.assert_awaited_once()  # only the first

    @pytest.mark.asyncio
    async def test_swallows_channel_exceptions(self) -> None:
        # Match TACFastAPIServer: per-channel errors don't fail the whole webhook.
        sms = _make_messaging_channel()
        sms.process_webhook = AsyncMock(side_effect=RuntimeError("boom"))
        server, _ = _build_server(messaging_channels=[sms])

        request = _make_request(CO_PAYLOAD, session_id="conv_abc")
        response = await server._dispatch_invoke(request)

        # Per-channel error swallowed → still 200 to Twilio (avoid retries).
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_invalid_json_returns_400(self) -> None:
        server, _ = _build_server(messaging_channels=[_make_messaging_channel()])

        request = MagicMock()
        request.state.session_id = None
        request.json = AsyncMock(side_effect=ValueError("bad json"))
        request.headers = {}
        response = await server._dispatch_invoke(request)

        assert response.status_code == 400


# ---------------------------------------------------------------------------
# Voice TwiML dispatch
# ---------------------------------------------------------------------------


class TestVoiceTwimlDispatch:
    @pytest.mark.asyncio
    async def test_voice_twiml_branch_calls_handle_incoming_call(self) -> None:
        voice = _make_voice_channel()
        voice.handle_incoming_call = AsyncMock(return_value="<Response>X</Response>")
        server, _ = _build_server(voice_channel=voice)

        body = {"CallSid": "CA123", "From": "+15555550000", "To": "+15555551111"}
        request = _make_request(body)
        response = await server._dispatch_invoke(request)

        assert response.status_code == 200
        assert response.media_type == "application/xml"
        assert b"<Response>X</Response>" in response.body
        voice.handle_incoming_call.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_voice_twiml_options_include_session_id(self) -> None:
        voice = _make_voice_channel()
        server, _ = _build_server(voice_channel=voice)

        request = _make_request({"CallSid": "CA123"})
        await server._dispatch_invoke(request)

        opts = voice.handle_incoming_call.await_args.kwargs["host_twiml_options"]
        assert isinstance(opts, TwiMLOptions)
        assert opts.websocket_url == "wss://test.example.com/twilio/ws?agent_session_id=CA123"
        # CustomParameters is a Pydantic model with built-in agent_session_id field;
        # it accepts a dict and stores the value on the typed attribute.
        assert opts.custom_parameters is not None
        assert opts.custom_parameters.agent_session_id == "CA123"
        assert opts.action_url == ("https://test.example.com/twilio/conversation-relay-callback")

    @pytest.mark.asyncio
    async def test_voice_twiml_url_encodes_call_sid(self) -> None:
        voice = _make_voice_channel()
        server, _ = _build_server(voice_channel=voice)

        await server._dispatch_invoke(_make_request({"CallSid": "CA/with weird?chars"}))

        opts = voice.handle_incoming_call.await_args.kwargs["host_twiml_options"]
        assert "CA%2Fwith%20weird%3Fchars" in opts.websocket_url

    @pytest.mark.asyncio
    async def test_voice_twiml_when_no_voice_channel_returns_400(self) -> None:
        sms = _make_messaging_channel()
        server, _ = _build_server(messaging_channels=[sms])

        body = {"CallSid": "CA123"}
        request = _make_request(body)
        response = await server._dispatch_invoke(request)

        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_voice_twiml_without_public_domain_returns_500(self) -> None:
        voice = _make_voice_channel()
        server, _ = _build_server(voice_channel=voice, public_domain="")

        response = await server._dispatch_invoke(_make_request({"CallSid": "CA1"}))

        assert response.status_code == 500

    @pytest.mark.asyncio
    async def test_apim_form_as_json_lists_are_flattened(self) -> None:
        # APIM's AsFormUrlEncodedContent emits each form value as a list.
        voice = _make_voice_channel()
        server, _ = _build_server(voice_channel=voice)

        body = {"CallSid": ["CA999"], "From": ["+15555550000"]}
        response = await server._dispatch_invoke(_make_request(body))

        assert response.status_code == 200
        opts = voice.handle_incoming_call.await_args.kwargs["host_twiml_options"]
        assert "agent_session_id=CA999" in opts.websocket_url


# ---------------------------------------------------------------------------
# WebSocket adapter
# ---------------------------------------------------------------------------


class TestStarletteWebSocketAdapter:
    @pytest.mark.asyncio
    async def test_accept_is_noop(self) -> None:
        from starlette.websockets import WebSocket

        ws = MagicMock(spec=WebSocket)
        ws.accept = AsyncMock()
        adapter = StarletteWebSocketAdapter(ws)

        await adapter.accept()
        ws.accept.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_receive_json_passes_through(self) -> None:
        from starlette.websockets import WebSocket

        ws = MagicMock(spec=WebSocket)
        ws.receive_json = AsyncMock(return_value={"type": "setup"})
        adapter = StarletteWebSocketAdapter(ws)

        result = await adapter.receive_json()
        assert result == {"type": "setup"}

    @pytest.mark.asyncio
    async def test_receive_json_translates_disconnect(self) -> None:
        from starlette.websockets import WebSocket, WebSocketDisconnect
        from tac.channels.websocket_protocol import WebSocketDisconnectError

        ws = MagicMock(spec=WebSocket)
        ws.receive_json = AsyncMock(side_effect=WebSocketDisconnect(code=1006))
        adapter = StarletteWebSocketAdapter(ws)

        with pytest.raises(WebSocketDisconnectError):
            await adapter.receive_json()

    @pytest.mark.asyncio
    async def test_send_text_translates_disconnect(self) -> None:
        from starlette.websockets import WebSocket, WebSocketDisconnect
        from tac.channels.websocket_protocol import WebSocketDisconnectError

        ws = MagicMock(spec=WebSocket)
        ws.send_text = AsyncMock(side_effect=WebSocketDisconnect(code=1006))
        adapter = StarletteWebSocketAdapter(ws)

        with pytest.raises(WebSocketDisconnectError):
            await adapter.send_text("hi")

    @pytest.mark.asyncio
    async def test_close_swallows_already_closed(self) -> None:
        from starlette.websockets import WebSocket

        ws = MagicMock(spec=WebSocket)
        ws.close = AsyncMock(side_effect=RuntimeError("already closed"))
        adapter = StarletteWebSocketAdapter(ws)

        await adapter.close()  # should not raise


# ---------------------------------------------------------------------------
# Voice WS dispatch
# ---------------------------------------------------------------------------


class TestVoiceWsDispatch:
    @pytest.mark.asyncio
    async def test_voice_ws_dispatches_to_voice_channel(self) -> None:
        voice = _make_voice_channel()
        server, _ = _build_server(voice_channel=voice)

        ws = MagicMock()
        await server._dispatch_voice_ws(ws)

        voice.handle_websocket.assert_awaited_once()
        adapter = voice.handle_websocket.await_args.args[0]
        assert isinstance(adapter, StarletteWebSocketAdapter)

    @pytest.mark.asyncio
    async def test_voice_ws_no_voice_channel_closes(self) -> None:
        server, _ = _build_server(messaging_channels=[_make_messaging_channel()])

        ws = MagicMock()
        ws.close = AsyncMock()
        await server._dispatch_voice_ws(ws)

        ws.close.assert_awaited_once()


# ---------------------------------------------------------------------------
# Idempotency LRU
# ---------------------------------------------------------------------------


class TestIdempotencyCache:
    def test_first_token_is_new(self) -> None:
        cache = _IdempotencyCache(capacity=10)
        assert cache.add_if_new("a") is True

    def test_repeat_token_is_not_new(self) -> None:
        cache = _IdempotencyCache(capacity=10)
        cache.add_if_new("a")
        assert cache.add_if_new("a") is False

    def test_evicts_oldest_at_capacity(self) -> None:
        cache = _IdempotencyCache(capacity=2)
        cache.add_if_new("a")
        cache.add_if_new("b")
        cache.add_if_new("c")  # evicts "a"
        assert cache.add_if_new("a") is True  # "a" is fresh again
