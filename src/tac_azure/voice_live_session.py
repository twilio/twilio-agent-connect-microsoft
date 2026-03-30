"""Single Voice Live WebSocket session.

Manages the lifecycle of one WebSocket connection to Azure AI Foundry
Voice Live.  Handles session configuration, text message exchange,
streaming responses, function calling, and interruptions.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from typing import Any

import websockets

from tac.core.logging import get_logger

from .voice_live_types import VoiceLiveConfig, VoiceLiveError

logger = get_logger(__name__)


class VoiceLiveSession:
    """Wraps a single WebSocket connection to Voice Live.

    Lifecycle::

        session = VoiceLiveSession(config, session_id)
        await session.connect()
        await session.configure()
        async for chunk in session.send_message_and_stream("Hello"):
            print(chunk)
        await session.close()

    The session maintains server-side conversation state.  Multiple user
    messages can be sent on the same connection and the model retains
    context across them.
    """

    def __init__(self, config: VoiceLiveConfig, session_id: str) -> None:
        self._config = config
        self._session_id = session_id
        self._ws: websockets.ClientConnection | None = None
        self._response_in_progress = False
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Open the WebSocket connection to Voice Live."""
        headers = await self._get_auth_headers()
        self._ws = await websockets.connect(
            self._config.ws_url,
            additional_headers=headers,
        )
        # Wait for session.created
        event = await self._recv_event()
        if event.get("type") != "session.created":
            raise VoiceLiveError(
                f"Expected session.created, got {event.get('type')}"
            )
        logger.info(
            "Voice Live session connected",
            session_id=self._session_id,
        )

    async def configure(
        self,
        *,
        instructions: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        **overrides: Any,
    ) -> None:
        """Send ``session.update`` to configure the session.

        Falls back to values from ``VoiceLiveConfig`` for any parameter
        not explicitly provided.
        """
        session_cfg: dict[str, Any] = {
            "modalities": self._config.modalities,
        }

        instr = instructions if instructions is not None else self._config.instructions
        if instr:
            session_cfg["instructions"] = instr

        tool_defs = tools if tools is not None else self._config.tools
        if tool_defs:
            session_cfg["tools"] = tool_defs

        if self._config.temperature is not None:
            session_cfg["temperature"] = self._config.temperature

        if self._config.max_response_output_tokens is not None:
            session_cfg["max_response_output_tokens"] = (
                self._config.max_response_output_tokens
            )

        session_cfg.update(overrides)

        await self._send_event({
            "type": "session.update",
            "session": session_cfg,
        })

        # Wait for session.updated confirmation
        event = await self._recv_event()
        if event.get("type") == "error":
            raise VoiceLiveError(
                event.get("error", {}).get("message", "session.update failed")
            )
        logger.info(
            "Voice Live session configured",
            session_id=self._session_id,
        )

    # ------------------------------------------------------------------
    # Messaging
    # ------------------------------------------------------------------

    async def send_message_and_stream(
        self, text: str
    ) -> AsyncGenerator[str, None]:
        """Send a user message and yield streaming text deltas.

        Handles function calling transparently: when the model requests a
        tool call, the session executes the tool, sends the result back,
        and resumes yielding text deltas from the continuation response.
        """
        async with self._lock:
            # 1. Add user message to conversation
            await self._send_event({
                "type": "conversation.item.create",
                "item": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": text}],
                },
            })

            # 2. Request a response
            await self._send_event({"type": "response.create"})
            self._response_in_progress = True

            # 3. Process server events until response.done
            try:
                async for chunk in self._process_response():
                    yield chunk
            finally:
                self._response_in_progress = False

    async def cancel_response(self) -> None:
        """Cancel an in-progress response (used for interruptions)."""
        if self._response_in_progress and self._ws:
            await self._send_event({"type": "response.cancel"})
            logger.info(
                "Cancelled Voice Live response",
                session_id=self._session_id,
            )

    async def close(self) -> None:
        """Close the WebSocket connection."""
        if self._ws:
            await self._ws.close()
            self._ws = None
            logger.info(
                "Voice Live session closed",
                session_id=self._session_id,
            )

    # ------------------------------------------------------------------
    # Internal: response processing
    # ------------------------------------------------------------------

    async def _process_response(self) -> AsyncGenerator[str, None]:
        """Process events for a single response cycle.

        Yields text deltas.  Handles function calls by executing the tool,
        sending the result, requesting a new response, and recursively
        processing the continuation.
        """
        func_name: str | None = None
        func_call_id: str | None = None
        func_args_parts: list[str] = []

        while True:
            event = await self._recv_event()
            event_type = event.get("type")

            if event_type == "response.text.delta":
                delta = event.get("delta", "")
                if delta:
                    yield delta

            elif event_type == "response.function_call_arguments.delta":
                func_args_parts.append(event.get("delta", ""))

            elif event_type == "response.function_call_arguments.done":
                func_name = event.get("name")
                func_call_id = event.get("call_id")
                # Don't break yet — wait for response.done

            elif event_type == "response.done":
                # If a function call was made, execute it and continue
                if func_name and func_call_id:
                    arguments = "".join(func_args_parts)
                    await self._execute_tool(func_name, func_call_id, arguments)

                    # Reset for next response cycle
                    func_name = None
                    func_call_id = None
                    func_args_parts = []

                    # Process the continuation response
                    async for chunk in self._process_response():
                        yield chunk
                return

            elif event_type == "error":
                error_msg = event.get("error", {}).get("message", "Unknown Voice Live error")
                raise VoiceLiveError(error_msg)

            # Ignore other event types (response.created, response.text.done,
            # response.output_item.added, rate_limits.updated, etc.)

    # ------------------------------------------------------------------
    # Internal: tool execution
    # ------------------------------------------------------------------

    async def _execute_tool(
        self, name: str, call_id: str, arguments: str
    ) -> None:
        """Execute a tool and send the result back to Voice Live."""
        executor = self._config.tool_executors.get(name)
        if executor is None:
            result = json.dumps({"error": f"Tool '{name}' not found"})
            logger.warning(
                "Tool executor not found",
                tool_name=name,
                session_id=self._session_id,
            )
        else:
            try:
                kwargs = json.loads(arguments) if arguments else {}
                raw_result = await executor(**kwargs)
                result = raw_result if isinstance(raw_result, str) else json.dumps(raw_result)
            except Exception as e:
                logger.error(
                    "Tool execution failed",
                    tool_name=name,
                    session_id=self._session_id,
                    exc_info=True,
                )
                result = json.dumps({"error": str(e)})

        logger.info(
            "Tool executed",
            tool_name=name,
            session_id=self._session_id,
        )

        # Send tool result
        await self._send_event({
            "type": "conversation.item.create",
            "item": {
                "type": "function_call_output",
                "call_id": call_id,
                "output": result,
            },
        })

        # Request continuation
        await self._send_event({"type": "response.create"})

    # ------------------------------------------------------------------
    # Internal: WebSocket helpers
    # ------------------------------------------------------------------

    async def _send_event(self, event: dict[str, Any]) -> None:
        """Send a JSON event to Voice Live."""
        if not self._ws:
            raise VoiceLiveError("WebSocket not connected")
        await self._ws.send(json.dumps(event))

    async def _recv_event(self) -> dict[str, Any]:
        """Receive and parse a single JSON event from Voice Live."""
        if not self._ws:
            raise VoiceLiveError("WebSocket not connected")
        raw = await self._ws.recv()
        return json.loads(raw)

    async def _get_auth_headers(self) -> dict[str, str]:
        """Build authentication headers for the WebSocket connection."""
        if self._config.api_key:
            return {"api-key": self._config.api_key}

        if self._config.credential:
            from azure.identity.aio import get_bearer_token_provider

            token = self._config.credential.get_token(
                "https://cognitiveservices.azure.com/.default"
            )
            if asyncio.iscoroutine(token):
                token = await token
            return {"Authorization": f"Bearer {token.token}"}

        raise VoiceLiveError(
            "VoiceLiveConfig must specify either api_key or credential"
        )
