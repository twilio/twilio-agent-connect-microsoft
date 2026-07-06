"""TACHostedAgentsApp: TAC server for Hosted Agents in Foundry Agent Service.

Hosted Agents (the Foundry Agent Service runtime under
``azure-ai-agentserver-invocations``) exposes exactly two endpoints —
``POST /invocations`` and ``WS /invocations_ws`` — bound to a fixed port,
with sandbox affinity keyed on an ``agent_session_id`` query parameter set
by APIM upstream. ``TACFastAPIServer``'s five-route layout doesn't fit
that contract, so this server is a peer implementation that overloads the
two fixed routes:

* ``/invocations`` dispatches by payload shape:
  - Twilio Conversation Orchestrator JSON envelope → fan out to every
    registered channel's ``process_webhook(body, idempotency_token)``,
    matching ``TACFastAPIServer.conversation_webhook``.
  - Twilio voice TwiML form (APIM converts form → JSON before this point;
    we detect by ``CallSid`` + absent ``eventType``) → call
    ``voice_channel.handle_incoming_call(...)`` and return the TwiML XML.
* ``/invocations_ws`` wraps the Starlette ``WebSocket`` in
  ``StarletteWebSocketAdapter`` and delegates to
  ``voice_channel.handle_websocket(...)``.

Auth (HMAC) is handled by APIM upstream, not here. The server validates
that ``agent_session_id`` (set by APIM from the upstream request) matches
the body's conversation/call ID for correctness — this is a sandbox-affinity
invariant, not a security check. It also dedups CO retries by Twilio's
``i-twilio-idempotency-token`` header in a bounded LRU.

For voice, ``agent_session_id`` reaches Foundry on the ``/invocations_ws``
upgrade as a query string parameter. To make that happen, this server
emits the wss URL with ``?agent_session_id=<CallSid>`` already attached
in the ``<ConversationRelay>`` TwiML, and additionally lists it as a
``<Parameter>`` child (Twilio CR appends those to the upgrade URL too —
belt + suspenders so APIM has at least one place to pluck it from).
"""

from __future__ import annotations

from collections import OrderedDict
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from tac.channels.base import BaseChannel
from tac.channels.websocket_protocol import WebSocketDisconnectError
from tac.core.logging import get_logger
from tac.core.tac import TAC
from tac.models.voice import TwiMLOptions

if TYPE_CHECKING:
    from tac.channels.messaging import MessagingChannel
    from tac.channels.voice import VoiceChannel

try:
    from azure.ai.agentserver.invocations import InvocationAgentServerHost
    from starlette.requests import Request
    from starlette.responses import JSONResponse, Response
    from starlette.websockets import WebSocket, WebSocketDisconnect
except ImportError as e:
    raise ImportError(
        "TACHostedAgentsApp requires the hosted-agents extra. Install with: "
        "pip install twilio-agent-connect-microsoft[hosted-agents]"
    ) from e


logger = get_logger(__name__)

# Twilio Conversation Orchestrator event types accepted on /invocations.
# COMMUNICATION_CREATED and CONVERSATION_UPDATED drive behavior; the others
# are accepted as no-ops (200, not 400) since CO can deliver them.
_CO_EVENT_TYPES = {
    "CONVERSATION_CREATED",
    "PARTICIPANT_ADDED",
    "COMMUNICATION_CREATED",
    "CONVERSATION_UPDATED",
}


class StarletteWebSocketAdapter:
    """Adapt a Starlette ``WebSocket`` to ``WebSocketProtocol``.

    Equivalent to ``tac.server.FastAPIWebSocketAdapter`` but for the raw
    Starlette WebSocket type that ``InvocationAgentServerHost`` exposes.
    Two Hosted-Agents specifics:

    * ``accept()`` is a no-op. ``InvocationAgentServerHost`` accepts the
      socket before the user handler runs; calling accept again raises.
      ``VoiceChannel.handle_websocket`` calls accept once at the top, so
      we silently swallow it.
    * ``WebSocketDisconnect`` (Starlette) is translated to
      ``WebSocketDisconnectError`` so VoiceChannel's framework-agnostic
      exception handling works.
    """

    def __init__(self, websocket: WebSocket) -> None:
        self._ws = websocket

    async def accept(self) -> None:
        return

    async def receive_json(self) -> Any:
        try:
            return await self._ws.receive_json()
        except WebSocketDisconnect as exc:
            raise WebSocketDisconnectError(str(exc)) from exc

    async def send_text(self, data: str) -> None:
        try:
            await self._ws.send_text(data)
        except WebSocketDisconnect as exc:
            raise WebSocketDisconnectError(str(exc)) from exc

    async def close(self) -> None:
        try:
            await self._ws.close()
        except Exception:
            # Already closed by the framework.
            pass


class _IdempotencyCache:
    """Bounded LRU set keyed on Twilio's ``i-twilio-idempotency-token``.

    Sandbox-local: Hosted Agents pins each conversation's retries to the
    same sandbox via ``agent_session_id`` affinity, so a process-local
    cache is sufficient to dedup retries. Bounded so a long-running
    sandbox can't grow it without limit.
    """

    def __init__(self, capacity: int = 4096) -> None:
        self._capacity = capacity
        self._seen: OrderedDict[str, None] = OrderedDict()

    def add_if_new(self, token: str) -> bool:
        """Return True if token was new (and is now recorded)."""
        if token in self._seen:
            self._seen.move_to_end(token)
            return False
        self._seen[token] = None
        if len(self._seen) > self._capacity:
            self._seen.popitem(last=False)
        return True


class TACHostedAgentsApp:
    """TAC server hosted inside Hosted Agents in Foundry Agent Service.

    Mirrors the public surface of ``TACFastAPIServer`` so it's a drop-in
    peer for users deploying to Foundry instead of Container Apps::

        connector = AgentFrameworkConnector(tac=tac, create_agent=...)
        server = TACHostedAgentsApp(
            tac=tac,
            voice_channel=connector.voice_channel,
            messaging_channels=[connector.sms_channel],
        )
        server.start()

    Voice URL config is read from ``tac.config`` (a ``TACConfig``):
    ``voice_public_domain`` should be the APIM hostname plus any path
    prefix the Twilio API points at (e.g.
    ``my-apim.azure-api.net/twilio``). The wss URL emitted to Twilio is
    ``wss://{voice_public_domain}{voice_websocket_path}?agent_session_id={CallSid}``;
    APIM rewrites that down to ``/invocations_ws`` on the Foundry backend.

    .. note::
        In TAC 2.x the voice URL fields moved from ``TACServerConfig`` onto
        ``TACConfig`` (``voice_public_domain`` / ``voice_websocket_path`` /
        ``voice_action_path``), so this server sources them from
        ``tac.config`` directly. There is no separate ``welcome_greeting``
        config field anymore — configure a greeting via
        ``VoiceChannelConfig.default_twiml_options`` on the voice channel, or
        rely on the voice channel's built-in default.
    """

    def __init__(
        self,
        tac: TAC,
        voice_channel: VoiceChannel | None = None,
        messaging_channels: list[MessagingChannel] | None = None,
        *,
        idempotency_cache_size: int = 4096,
    ) -> None:
        self.tac = tac
        self.voice_channel = voice_channel
        self.messaging_channels: list[MessagingChannel] = messaging_channels or []

        # Channels that should receive CO webhook fan-out, mirroring
        # TACFastAPIServer.conversation_webhook.
        self._webhook_channels: list[BaseChannel] = []
        if self.voice_channel is not None:
            self._webhook_channels.append(self.voice_channel)
        self._webhook_channels.extend(self.messaging_channels)

        if self.voice_channel is not None and not self.tac.config.voice_public_domain:
            logger.warning(
                "voice_public_domain is not set — voice URLs will be malformed. "
                "Set TWILIO_VOICE_PUBLIC_DOMAIN environment variable."
            )

        self._idempotency = _IdempotencyCache(capacity=idempotency_cache_size)

        self.app = InvocationAgentServerHost()
        self._register_handlers(self.app)

    @staticmethod
    def _flatten_form_values(obj: Any) -> dict[str, str]:
        """Flatten APIM's form-as-JSON shape (``{"key": ["value"]}``).

        APIM's ``AsFormUrlEncodedContent()`` policy emits each form key
        as a list (forms allow repeats). We take the first value of each
        list so downstream code sees a normal flat dict.
        """
        out: dict[str, str] = {}
        if isinstance(obj, dict):
            for k, v in obj.items():
                if isinstance(v, list) and v:
                    out[k] = str(v[0])
                elif isinstance(v, (str, int, float, bool)):
                    out[k] = str(v)
        return out

    @staticmethod
    def _looks_like_co_webhook(body: dict[str, Any]) -> bool:
        return body.get("eventType") in _CO_EVENT_TYPES and isinstance(body.get("data"), dict)

    @staticmethod
    def _co_conversation_id(body: dict[str, Any]) -> str | None:
        data = body.get("data")
        if not isinstance(data, dict):
            return None
        conv_id = data.get("conversationId") or data.get("id")
        return conv_id if isinstance(conv_id, str) else None

    def _build_voice_websocket_url(self, call_sid: str) -> str:
        cfg = self.tac.config
        return (
            f"wss://{cfg.voice_public_domain}{cfg.voice_websocket_path}"
            f"?agent_session_id={quote(call_sid, safe='')}"
        )

    def _build_voice_action_url(self) -> str | None:
        cfg = self.tac.config
        if not cfg.voice_public_domain:
            return None
        return f"https://{cfg.voice_public_domain}{cfg.voice_action_path}"

    def _register_handlers(self, app: InvocationAgentServerHost) -> None:
        @app.invoke_handler
        async def handle_invoke(request: Request) -> Response:
            return await self._dispatch_invoke(request)

        if self.voice_channel is not None:

            @app.ws_handler
            async def handle_voice_ws(websocket: WebSocket) -> None:
                await self._dispatch_voice_ws(websocket)

    async def _dispatch_invoke(self, request: Request) -> Response:
        session_id = getattr(request.state, "session_id", None)

        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "invalid JSON"}, status_code=400)

        if not isinstance(body, dict):
            return JSONResponse({"error": "expected JSON object body"}, status_code=400)

        flat = self._flatten_form_values(body)

        # Voice TwiML branch: presence of CallSid + absent eventType.
        if flat.get("CallSid") and not body.get("eventType"):
            return await self._handle_voice_twiml(flat, session_id)

        return await self._handle_co_webhook(request, body, session_id)

    async def _handle_voice_twiml(self, flat: dict[str, str], session_id: str | None) -> Response:
        if self.voice_channel is None:
            return JSONResponse({"error": "voice channel not configured"}, status_code=400)
        if not self.tac.config.voice_public_domain:
            return JSONResponse({"error": "TWILIO_VOICE_PUBLIC_DOMAIN is not set"}, status_code=500)
        call_sid = flat["CallSid"]
        try:
            websocket_url = self._build_voice_websocket_url(call_sid)
            # Per-call transport facts supplied by this host (affinity-routed
            # WebSocket URL + the CallSid echoed as a custom parameter). These
            # layer *below* ``VoiceChannelConfig.default_twiml_options`` — we
            # only pass facts nothing else should override.
            #
            # NOTE: build the kwargs so we never set a field to ``None``. In
            # TAC 2.x, TwiML options merge per-field via ``model_fields_set``,
            # so an explicit ``None`` would *suppress* the channel's default
            # (e.g. the default welcome greeting / conversation configuration)
            # rather than fall through to it. Omit unset fields entirely.
            #
            # The welcome greeting is intentionally NOT set here: configure it
            # on the voice channel via ``VoiceChannelConfig.default_twiml_options``
            # (or rely on the channel's built-in default). There is no
            # server-level greeting config field in TAC 2.x.
            host_options_kwargs: dict[str, Any] = {
                "websocket_url": websocket_url,
                "action_url": self._build_voice_action_url(),
                "custom_parameters": {"agent_session_id": call_sid},
            }
            twiml_xml = await self.voice_channel.handle_incoming_call(
                host_twiml_options=TwiMLOptions(**host_options_kwargs)
            )
        except Exception:
            logger.error("voice TwiML generation failed", exc_info=True)
            return JSONResponse({"error": "twiml_generation_failed"}, status_code=500)
        logger.info(
            "Generated TwiML",
            extra={
                "session_id": session_id,
                "call_sid": call_sid,
                "websocket_url": websocket_url,
            },
        )
        return Response(content=twiml_xml, media_type="application/xml")

    async def _handle_co_webhook(
        self, request: Request, body: dict[str, Any], session_id: str | None
    ) -> Response:
        if not self._looks_like_co_webhook(body):
            logger.warning(
                "rejecting unrecognized payload",
                extra={
                    "session_id": session_id,
                    "event_type": body.get("eventType"),
                },
            )
            return JSONResponse(
                {
                    "error": (
                        "Unsupported payload. Expected a Twilio Conversation "
                        "Orchestrator webhook with eventType in "
                        "PARTICIPANT_ADDED | COMMUNICATION_CREATED | "
                        "CONVERSATION_UPDATED, or a Twilio voice TwiML webhook."
                    )
                },
                status_code=400,
            )

        body_conv_id = self._co_conversation_id(body)
        if session_id and body_conv_id and session_id != body_conv_id:
            logger.error(
                "agent_session_id mismatch — APIM routing bug",
                extra={"agent_session_id": session_id, "conversation_id": body_conv_id},
            )
            return JSONResponse(
                {"error": "agent_session_id does not match conversationId in body"},
                status_code=400,
            )

        idempotency_token = request.headers.get("i-twilio-idempotency-token")
        if idempotency_token and not self._idempotency.add_if_new(idempotency_token):
            logger.info(
                "duplicate webhook suppressed",
                extra={"idempotency_token": idempotency_token, "session_id": session_id},
            )
            return JSONResponse(
                {"status": "duplicate", "idempotency_token": idempotency_token},
                status_code=200,
            )

        if not self._webhook_channels:
            logger.warning("no channels registered to handle CO webhook")
            return JSONResponse({"error": "no channels configured"}, status_code=400)

        # Synchronous fan-out: process before returning 200. Hosted
        # Agents holds the sandbox warm for the duration of /invocations,
        # so this is the simplest correct behavior. (TACFastAPIServer
        # uses background tasks because uvicorn keeps running after the
        # response. Here, returning 200 too early risks the sandbox
        # suspending mid-LLM-call.)
        import asyncio

        await asyncio.gather(
            *(
                self._process_webhook_with_error_handling(channel, body, idempotency_token)
                for channel in self._webhook_channels
            )
        )
        return JSONResponse(
            {"status": "ok", "session_id": session_id, "event_type": body.get("eventType")}
        )

    @staticmethod
    async def _process_webhook_with_error_handling(
        channel: BaseChannel, webhook_data: dict[str, Any], idempotency_token: str | None
    ) -> None:
        try:
            await channel.process_webhook(webhook_data, idempotency_token)
        except Exception:
            logger.error(
                "Error processing webhook in channel",
                extra={"channel": channel.get_channel_name()},
                exc_info=True,
            )

    async def _dispatch_voice_ws(self, websocket: WebSocket) -> None:
        if self.voice_channel is None:
            await websocket.close(code=1011)
            return
        try:
            adapter = StarletteWebSocketAdapter(websocket)
            await self.voice_channel.handle_websocket(adapter)
        except WebSocketDisconnect:
            logger.info("voice WS disconnected")
        except WebSocketDisconnectError:
            logger.info("voice WS disconnected")
        except Exception:
            logger.error("voice WS handler crashed", exc_info=True)
            raise

    def start(self) -> None:
        """Run the Hosted Agents server until exit.

        ``InvocationAgentServerHost.run()`` binds to ``0.0.0.0`` on the
        port the platform passes via ``$PORT``.
        """
        logger.info("Starting TAC Hosted Agents Server")
        self.app.run()
