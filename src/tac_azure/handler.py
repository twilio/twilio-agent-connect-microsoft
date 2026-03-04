"""
OmniChannel Handler for Agent Framework + TAC

Ported from strands_communications.twilio.omnichannel — adapted for Microsoft Agent Framework.

Key differences from Strands version:
- No AgentProxy abstraction — handler calls agent.run() directly
- SMS: handler internally manages the on_message_ready callback
- Voice: handler manages internally via create_agent + streaming
- create_agent returns an AgentLike object (anything with async run())
- Explicit ``channels`` parameter controls which channels are initialised

Conversation history:
- The handler passes an ``AgentSession`` to every ``agent.run()`` call so
  that Agent Framework can load/save conversation history automatically.
- Voice: agent + session are cached in-memory for the duration of the
  WebSocket call.  The same agent handles all utterances within a single
  call, and history accumulates naturally.  The session is also persisted
  to the ``SessionStore`` in the background (fire-and-forget) after each
  utterance and on disconnect, enabling auditing and persistence of
  Foundry thread IDs without impacting voice latency.
- SMS: a ``SessionStore`` persists the ``AgentSession`` between messages.
  Before each ``agent.run()``, the handler loads the session from the store
  (or creates a new one); after the run it saves the session back.  This
  enables conversation continuity across messages for all provider types:
    - Foundry Agent Service: the server-side ``thread_id`` (stored as
      ``session.service_session_id``) is preserved so subsequent messages
      reuse the same thread.
    - Responses API / Chat Completions: session state (including messages
      from ``InMemoryHistoryProvider``) is preserved across messages.
  The default ``InMemorySessionStore`` works for single-instance
  deployments.  For horizontal scaling, supply a persistent store
  (Redis, CosmosDB, etc.) via the ``session_store`` parameter.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Callable
from typing import TYPE_CHECKING, Any

from agent_framework import AgentSession
from fastapi import HTTPException, WebSocket
from tac.session import ThreadSafeSessionManager
from tac.channels.sms import SMSChannel
from tac.channels.voice import VoiceChannel
from tac.core.logging import get_logger
from tac.models.session import ConversationSession

from .types import AgentLike, InMemorySessionStore, SessionStore
from .utils import format_memory_context

if TYPE_CHECKING:
    from tac.models.tac import TACMemoryResponse

logger = get_logger(__name__)


class OmniChannelHandler:
    """
    Handler for Twilio channels (Voice and SMS) with Agent Framework agents.

    Both voice and SMS flows are fully managed internally.  The developer
    supplies a ``create_agent`` factory and, optionally, an ``on_message``
    hook for SMS message augmentation.

    Conversation history is managed via Agent Framework's ``AgentSession``.
    For voice, the agent and session persist in-memory for the duration of
    the WebSocket call, with background saves to the ``SessionStore`` after
    each utterance for persistence/auditing.  For SMS, the session is loaded
    from and saved to the ``SessionStore`` on every message.

    Args:
        tac: TAC instance.
        create_agent: ``(session: ConversationSession) -> AgentLike``.
        channels: List of channels to enable.  Defaults to ``["voice", "sms"]``.
        public_domain: Public domain for WebSocket/callback URLs (e.g. ngrok domain).
            **Required** when ``"voice"`` is in *channels*.
        welcome_greeting: Initial greeting for voice callers.
        on_message: Optional hook called before ``agent.run()`` for SMS.
            Signature: ``(user_message, context, memory_response) -> str``.
            When *None*, defaults to ``format_memory_context(memory, msg)``.
        auto_retrieve_memory: If *True* (default), TAC channels auto-retrieve
            memory before invoking callbacks.  Set to *False* to skip the
            latency of auto-retrieval (use the memory recall tool instead).
        session_store: Persistence layer for ``AgentSession`` objects.
            Used for SMS session continuity across messages and for
            background persistence of voice sessions (auditing, Foundry
            thread IDs).  Defaults to ``InMemorySessionStore`` (suitable
            for single-instance deployments).  For horizontal scaling,
            provide a persistent implementation (Redis, CosmosDB, etc.).
        websocket_path: WebSocket path (used in TwiML generation).
    """

    def __init__(
        self,
        tac: Any,
        create_agent: Callable[[ConversationSession], AgentLike],
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
        session_store: SessionStore | None = None,
        websocket_path: str = "/ws",
    ):
        self.tac = tac
        self.create_agent = create_agent
        self.channels: list[str] = channels if channels is not None else ["voice", "sms"]
        self.public_domain = public_domain
        self.welcome_greeting = welcome_greeting or "Hello! How can I help you today!"
        self.websocket_path = websocket_path
        self.on_message = on_message
        self.session_store: SessionStore = (
            session_store if session_store is not None else InMemorySessionStore()
        )

        # -- Validate configuration ------------------------------------------
        if "voice" in self.channels and not self.public_domain:
            raise ValueError(
                "public_domain is required when 'voice' is in channels. "
                "Provide the public domain (e.g. your ngrok domain) used for "
                "WebSocket and callback URLs."
            )

        # -- Voice channel (only when enabled) --------------------------------
        self._voice_agents: dict[str, AgentLike] = {}
        self._voice_sessions: dict[str, AgentSession] = {}
        self.tac_session_manager: ThreadSafeSessionManager | None = None
        self.voice_channel: VoiceChannel | None = None

        if "voice" in self.channels:
            self.tac_session_manager = ThreadSafeSessionManager()
            self.voice_channel = VoiceChannel(
                tac=self.tac,
                session_manager=self.tac_session_manager,
                auto_retrieve_memory=auto_retrieve_memory,
            )

        # -- SMS channel (only when enabled) ----------------------------------
        self.sms_channel: SMSChannel | None = None

        if "sms" in self.channels:
            self.sms_channel = SMSChannel(
                tac=self.tac,
                auto_retrieve_memory=auto_retrieve_memory,
            )

        # Register a single unified callback that dispatches by channel
        self.tac.on_message_ready(self._handle_message)

        logger.info(
            "OmniChannel handler initialized (Agent Framework)",
            channels=self.channels,
        )

    # -------------------------------------------------------------------------
    # Unified message callback
    # -------------------------------------------------------------------------

    async def _handle_message(
        self,
        user_message: str,
        context: ConversationSession,
        memory_response: TACMemoryResponse | None,
    ) -> None:
        """Unified callback registered with ``tac.on_message_ready()``.

        Dispatches to the appropriate channel handler based on
        ``context.channel``.
        """
        if context.channel == "sms":
            await self._handle_sms_message(user_message, context, memory_response)
        elif context.channel == "voice":
            await self._handle_voice_message(user_message, context, memory_response)
        else:
            logger.warning(
                "Unknown channel in _handle_message",
                channel=context.channel,
                conversation_id=context.conversation_id,
            )

    # -------------------------------------------------------------------------
    # Internal voice handler (called via _handle_message)
    # -------------------------------------------------------------------------

    async def _handle_voice_message(
        self,
        user_message: str,
        context: ConversationSession,
        memory_response: TACMemoryResponse | None,
    ) -> None:
        """Handle a voice message via the unified on_message_ready callback.

        Streams the agent response back through the voice channel.
        """
        if self.voice_channel is None:
            return

        await self.voice_channel.send_response(
            context.conversation_id,
            self._stream_response(user_message, context.conversation_id),
        )

    # -------------------------------------------------------------------------
    # Internal SMS handler
    # -------------------------------------------------------------------------

    async def _handle_sms_message(
        self,
        user_message: str,
        context: ConversationSession,
        memory_response: TACMemoryResponse | None,
    ) -> None:
        """Internal callback registered with ``tac.on_message_ready()``.

        Creates an agent, restores the ``AgentSession`` from the session
        store (or creates a new one), runs the agent, and persists the
        session back to the store.  This enables conversation continuity
        across messages for all provider types (Foundry threads, Responses
        API history, etc.).
        """
        if not context or context.channel != "sms":
            return

        assert self.sms_channel is not None  # guaranteed by __init__

        # Apply on_message hook (or default to format_memory_context)
        if self.on_message is not None:
            augmented_message = self.on_message(user_message, context, memory_response)
        else:
            augmented_message = format_memory_context(memory_response, user_message)

        agent = self.create_agent(context)

        # Restore session from store (preserves Foundry thread_id,
        # message history, etc.) or create a fresh one.
        af_session = await self.session_store.load(context.conversation_id)
        if af_session is None:
            af_session = AgentSession(session_id=context.conversation_id)

        try:
            result = await agent.run(augmented_message, session=af_session)
            await self.sms_channel.send_response(
                context.conversation_id, result.text, role="assistant"
            )
        except Exception:
            logger.error(
                "Error processing SMS message",
                conversation_id=context.conversation_id,
                channel="sms",
                exc_info=True,
            )
            await self.sms_channel.send_response(
                context.conversation_id,
                "Sorry, something went wrong. Please try again.",
                role="assistant",
            )
        finally:
            # Always persist the session — even on error the session may
            # contain updated state (e.g. a newly created Foundry thread).
            await self.session_store.save(context.conversation_id, af_session)

    # -------------------------------------------------------------------------
    # Voice flow
    # -------------------------------------------------------------------------

    async def _stream_response(
        self, prompt: str, session_id: str
    ) -> AsyncGenerator[str, None]:
        """Stream generator that yields Agent Framework streaming responses.

        Integrates Agent Framework with TAC's streaming interface.
        Creates agent lazily on first call, reuses for subsequent utterances
        in the same call, and marks for cleanup when done.

        The same AgentSession is passed on every utterance so conversation
        history accumulates within the call.

        Args:
            prompt: The user's message to send to the agent
            session_id: The conversation_id from TAC (used as agent session_id)

        Yields:
            Text chunks from the agent streaming response (plain strings)
        """
        prompt_preview = prompt[:100] + "..." if len(prompt) > 100 else prompt
        logger.info(
            f"USER MESSAGE | {prompt_preview}",
            conversation_id=session_id,
            channel="voice",
        )

        agent = self._get_or_create_voice_agent(session_id)
        af_session = self._get_or_create_voice_session(session_id)

        full_response: list[str] = []

        try:
            async for chunk in agent.run(prompt, stream=True, session=af_session):
                if hasattr(chunk, "text") and chunk.text:
                    full_response.append(chunk.text)
                    yield chunk.text

            response_text = "".join(full_response)
            response_preview = (
                response_text[:100] + "..." if len(response_text) > 100 else response_text
            )
            logger.info(
                f"AI RESPONSE | {response_preview}",
                conversation_id=session_id,
                channel="voice",
            )

            # Persist session in the background (non-blocking) for
            # auditing and Foundry thread_id durability.
            self._background_save_session(session_id, af_session)
        except GeneratorExit:
            logger.info("Stream interrupted, cleaning up agent", session_id=session_id)
            self._cleanup_voice_agent(session_id)
            raise
        except Exception as e:
            logger.error(
                "Error during streaming",
                session_id=session_id,
                exc_info=True,
                error=str(e),
            )
            self._cleanup_voice_agent(session_id)
            raise

    def _get_or_create_voice_agent(self, conversation_id: str) -> AgentLike:
        """Get existing voice agent or create new one for conversation."""
        if conversation_id not in self._voice_agents:
            logger.info("Creating new voice agent", conversation_id=conversation_id)
            assert self.voice_channel is not None
            session = self.voice_channel._conversations[conversation_id]
            if session.profile_id is None:
                logger.error(
                    "Cannot create agent: profile_id is None",
                    conversation_id=conversation_id,
                )
                raise HTTPException(
                    status_code=409,
                    detail="Cannot create agent: profile_id is not set for this conversation.",
                )
            self._voice_agents[conversation_id] = self.create_agent(session)
        return self._voice_agents[conversation_id]

    def _get_or_create_voice_session(self, conversation_id: str) -> AgentSession:
        """Get existing voice AgentSession or create a new one.

        Voice sessions are cached in-memory for the duration of the
        WebSocket call so history accumulates across utterances.
        """
        if conversation_id not in self._voice_sessions:
            self._voice_sessions[conversation_id] = AgentSession(
                session_id=conversation_id
            )
            logger.info(
                "Created new voice AgentSession",
                conversation_id=conversation_id,
            )
        return self._voice_sessions[conversation_id]

    def _background_save_session(
        self, session_id: str, session: AgentSession
    ) -> None:
        """Fire-and-forget save of a session to the store.

        Does not block the calling coroutine.  Errors are logged but
        do not propagate — voice latency is never impacted.
        """

        async def _save() -> None:
            try:
                await self.session_store.save(session_id, session)
            except Exception:
                logger.error(
                    "Background session save failed",
                    session_id=session_id,
                    exc_info=True,
                )

        asyncio.create_task(_save())

    def _cleanup_voice_agent(self, conversation_id: str) -> None:
        """Clean up voice agent and session when WebSocket disconnects."""
        agent = self._voice_agents.pop(conversation_id, None)
        af_session = self._voice_sessions.pop(conversation_id, None)
        if agent:
            logger.info(
                "Cleaning up voice agent and session",
                conversation_id=conversation_id,
            )
            del agent
        if af_session:
            # Final persist to session store before discarding.
            self._background_save_session(conversation_id, af_session)
            del af_session
        if not agent:
            logger.warning(
                "No voice agent found to cleanup", conversation_id=conversation_id
            )

    # -------------------------------------------------------------------------
    # Public methods (route handlers)
    # -------------------------------------------------------------------------

    async def handle_twiml_request(self, from_number: str, to_number: str, call_sid: str) -> str:
        """Handle incoming TwiML requests for call setup.

        Args:
            from_number: The phone number of the caller
            to_number: The phone number being called
            call_sid: The Twilio call SID

        Returns:
            TwiML XML content string

        Raises:
            RuntimeError: If voice channel is not enabled.
        """
        if self.voice_channel is None:
            raise RuntimeError(
                "Voice channel is not enabled. Add 'voice' to channels to use this method."
            )

        websocket_url = f"wss://{self.public_domain}{self.websocket_path}"
        callback_url = f"https://{self.public_domain}/conversation-relay-callback"

        clean_from_number = from_number.replace("client:", "") if from_number else ""
        clean_to_number = to_number.replace("client:", "") if to_number else ""

        return await self.voice_channel.handle_incoming_call(
            to_number=clean_to_number,
            from_number=clean_from_number,
            options={
                "websocket_url": websocket_url,
                "action_url": callback_url,
                "welcome_greeting": self.welcome_greeting,
            },
            call_sid=call_sid,
        )

    async def handle_websocket_connection(self, websocket: WebSocket) -> None:
        """Handle WebSocket connection for audio streaming.

        Creates agent on connect, manages call duration, cleans up on disconnect.

        Raises:
            RuntimeError: If voice channel is not enabled.
        """
        if self.voice_channel is None:
            raise RuntimeError(
                "Voice channel is not enabled. Add 'voice' to channels to use this method."
            )

        logger.info("WebSocket connection established")

        try:
            await self.voice_channel.handle_websocket(websocket)
        finally:
            logger.info(
                "WebSocket disconnected, agents cleaned up via stream generator completion"
            )

    async def handle_sms_webhook(
        self,
        webhook_data: dict[str, Any],
        idempotency_token: str | None = None,
    ) -> None:
        """Handle incoming SMS webhook from Twilio.

        Args:
            webhook_data: The parsed webhook payload dict
            idempotency_token: Optional Twilio idempotency token from the
                ``i-twilio-idempotency-token`` request header.

        Raises:
            RuntimeError: If SMS channel is not enabled.
        """
        if self.sms_channel is None:
            raise RuntimeError(
                "SMS channel is not enabled. Add 'sms' to channels to use this method."
            )

        try:
            logger.info(
                "Calling sms_channel.process_webhook",
                channel="sms",
                webhook_data=webhook_data,
            )
            await self.sms_channel.process_webhook(webhook_data, idempotency_token)
        except Exception as e:
            logger.error(
                "Error processing SMS webhook",
                channel="sms",
                exc_info=True,
                error=str(e),
            )
