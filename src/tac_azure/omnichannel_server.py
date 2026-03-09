"""
Batteries-included FastAPI server wrapping OmniChannelHandler.

Provides pre-wired routes for voice TwiML, WebSocket, SMS webhooks,
conversation-relay callbacks, and health checks.  Webhook signature
validation is supported when ``validate_webhooks=True``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

import uvicorn
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import JSONResponse, Response
from tac.core.logging import get_logger

from .omnichannel_handler import OmniChannelHandler
from .types import AgentSessionStore

if TYPE_CHECKING:
    from agent_framework import Agent
    from tac.models.tac import TACMemoryResponse
    from tac.models.session import ConversationSession

logger = get_logger(__name__)


class OmniChannelServer:
    """Batteries-included FastAPI server for Agent Framework + TAC.

    Wraps :class:`OmniChannelHandler` with pre-wired routes so the
    developer only needs to supply ``tac``, ``create_agent``, and
    (optionally) ``public_domain``.

    Args:
        tac: TAC instance.
        create_agent: ``(session: ConversationSession) -> Agent``.
        channels: Channels to enable.  Defaults to ``["voice", "sms"]``.
        public_domain: Required when ``"voice"`` is in *channels*.
        welcome_greeting: Initial voice greeting.
        on_message: SMS message augmentation hook.
        auto_retrieve_memory: Pass through to TAC channels.
        session_store: Persistence layer for ``AgentSession`` between
            SMS messages.  Defaults to in-memory.  For horizontal scaling,
            provide a persistent implementation.
        validate_webhooks: When *True* (default), validate Twilio
            webhook signatures on SMS and TwiML routes using the auth
            token from ``tac.config.twilio_auth_token``.
        websocket_path: WebSocket endpoint path.
        twiml_path: TwiML endpoint path.
        sms_path: SMS webhook endpoint path.
        host: Bind address.
        port: Bind port.
        on_startup: Optional async callback invoked once at server
            startup (before serving requests).  Useful for async
            initialisation such as knowledge-tool creation.
    """

    def __init__(
        self,
        tac: Any,
        create_agent: Callable[[ConversationSession], Agent],
        channels: list[str] | None = None,
        public_domain: str | None = None,
        welcome_greeting: str | None = None,
        on_message: (
            Callable[
                [str, ConversationSession, TACMemoryResponse | None],
                str,
            ]
            | None
        ) = None,
        auto_retrieve_memory: bool = True,
        session_store: AgentSessionStore | None = None,
        validate_webhooks: bool = True,
        websocket_path: str = "/ws",
        twiml_path: str = "/twiml",
        sms_path: str = "/webhook",
        host: str = "0.0.0.0",
        port: int = 8000,
        on_startup: Callable[[], Awaitable[None]] | None = None,
    ):
        self.tac = tac
        self.validate_webhooks = validate_webhooks
        self.twiml_path = twiml_path
        self.sms_path = sms_path
        self.host = host
        self.port = port
        self.on_startup = on_startup

        self.handler = OmniChannelHandler(
            tac=tac,
            create_agent=create_agent,
            channels=channels,
            public_domain=public_domain,
            welcome_greeting=welcome_greeting,
            on_message=on_message,
            auto_retrieve_memory=auto_retrieve_memory,
            session_store=session_store,
            websocket_path=websocket_path,
        )

        self._app: FastAPI | None = None
        self._server: uvicorn.Server | None = None

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    @property
    def app(self) -> FastAPI:
        """Return (and lazily create) the FastAPI application."""
        if self._app is None:
            self._app = self._create_app()
        return self._app

    def serve(self) -> None:
        """Start the server (blocking)."""
        logger.info("Starting server", host=self.host, port=self.port)
        uvicorn.run(self.app, host=self.host, port=self.port, log_level="info")

    async def serve_async(self) -> None:
        """Start the server asynchronously."""
        logger.info("Starting server (async)", host=self.host, port=self.port)
        config = uvicorn.Config(self.app, host=self.host, port=self.port, log_level="info")
        self._server = uvicorn.Server(config)
        await self._server.serve()

    def stop(self) -> None:
        """Initiate graceful shutdown."""
        if self._server:
            self._server.should_exit = True
            logger.info("Server shutdown initiated")

    # ------------------------------------------------------------------
    # Webhook signature validation
    # ------------------------------------------------------------------

    async def _validate_signature(self, request: Request, body: bytes) -> bool:
        """Validate Twilio webhook signature.

        Delegates to TAC's ``validate_twilio_webhook`` which handles proxy
        headers (``X-Forwarded-Proto``, ``X-Forwarded-Host``) and
        comma-separated values for multi-proxy environments.

        Returns True if valid or validation is disabled.
        """
        if not self.validate_webhooks:
            return True

        try:
            from tac.server.webhook import validate_twilio_webhook

            # For form-encoded requests (TwiML), pass the form dict.
            # For JSON requests (SMS webhook), pass the body string.
            content_type = request.headers.get("content-type", "")
            if "application/x-www-form-urlencoded" in content_type:
                form = await request.form()
                body_for_validation: str | dict[str, str] = dict(form)
            else:
                body_for_validation = body.decode("utf-8") if body else ""

            return validate_twilio_webhook(
                request=request,
                auth_token=self.tac.config.twilio_auth_token,
                body=body_for_validation,
            )
        except ImportError:
            raise RuntimeError(
                "Webhook validation is enabled but the 'twilio' package is not "
                "installed. Either install it (pip install twilio) or set "
                "validate_webhooks=False to disable signature checking."
            )
        except Exception:
            logger.error("Webhook signature validation error", exc_info=True)
            return False

    # ------------------------------------------------------------------
    # App creation
    # ------------------------------------------------------------------

    def _create_app(self) -> FastAPI:
        """Build the FastAPI application with all routes."""
        from contextlib import asynccontextmanager

        server = self  # capture for closures

        @asynccontextmanager
        async def lifespan(app: FastAPI):
            if server.on_startup:
                await server.on_startup()
            yield

        app = FastAPI(title="TAC Agent Framework Server", lifespan=lifespan)

        # -- Voice routes (only when enabled) ---------------------------------
        if "voice" in self.handler.channels:

            @app.post(self.twiml_path)
            async def post_twiml(request: Request) -> Response:
                if server.validate_webhooks:
                    body = await request.body()
                    if not await server._validate_signature(request, body):
                        return Response(content="Forbidden", status_code=403)

                form = await request.form()
                xml = await server.handler.handle_twiml_request(
                    form["From"], form["To"], form["CallSid"]
                )
                return Response(content=xml, media_type="application/xml")

            @app.websocket(self.handler.websocket_path)
            async def websocket_endpoint(websocket: WebSocket) -> None:
                await server.handler.handle_websocket_connection(websocket)

            @app.post("/conversation-relay-callback")
            async def conversation_relay_callback(request: Request) -> Response:
                assert server.handler.voice_channel is not None
                form_data = await request.form()
                payload_dict = {key: str(value) for key, value in form_data.items()}
                result = await server.handler.voice_channel.handle_conversation_relay_callback(
                    payload_dict
                )
                if result is not None:
                    return Response(content=result, media_type="text/xml")
                return Response(content="OK", media_type="text/plain")

        # -- SMS routes (only when enabled) -----------------------------------
        if "sms" in self.handler.channels:

            @app.post(self.sms_path)
            async def post_sms(request: Request):
                if server.validate_webhooks:
                    body = await request.body()
                    if not await server._validate_signature(request, body):
                        return Response(content="Forbidden", status_code=403)

                webhook_data = await request.json()
                idempotency_token = request.headers.get("i-twilio-idempotency-token")

                async def _process():
                    try:
                        await server.handler.handle_sms_webhook(
                            webhook_data, idempotency_token
                        )
                    except Exception:
                        logger.error("Webhook processing failed", exc_info=True)

                asyncio.create_task(_process())
                return JSONResponse(content={"status": "ok"})

        # -- Always available routes ------------------------------------------

        @app.get("/health")
        async def health_check():
            return {
                "status": "healthy",
                "server": "tac-azure",
                "channels": server.handler.channels,
            }

        return app
