"""
Agent Framework Bridge for TAC

Bridge logic (agent lifecycle, session management, tool factories) for Microsoft
Agent Framework.  HTTP/WebSocket routing is delegated to ``TACFastAPIServer`` from the
``tac`` package.

Key design:
- ``create_agent`` factory returns an Agent Framework ``Agent``
- Voice and SMS channel instances are exposed as ``voice_channel`` / ``sms_channel``
  — pass whichever you need to ``TACFastAPIServer`` to wire up routing

Conversation history:
- The bridge passes an ``AgentSession`` to every ``agent.run()`` call so
  that Agent Framework can load/save conversation history automatically.
- Voice: agent + session are cached in-memory for the duration of the
  WebSocket call.  The same agent handles all utterances within a single
  call, and history accumulates naturally.  The session is also persisted
  to the ``AgentSessionStore`` in the background (fire-and-forget) after each
  utterance and on disconnect, enabling auditing and persistence of
  Foundry thread IDs without impacting voice latency.
- SMS: an ``AgentSessionStore`` persists the ``AgentSession`` between messages.
  Before each ``agent.run()``, the bridge loads the session from the store
  (or creates a new one); after the run it saves the session back.  This
  enables conversation continuity across messages for all provider types:
    - Foundry Agent Service: the server-side ``thread_id`` (stored as
      ``session.service_session_id``) is preserved so subsequent messages
      reuse the same thread.
    - Responses API / Chat Completions: session state (including messages
      from ``InMemoryHistoryProvider``) is preserved across messages.
  The default ``InMemoryAgentSessionStore`` works for single-instance
  deployments.  For horizontal scaling, supply a persistent store
  (Redis, CosmosDB, etc.) via the ``session_store`` parameter.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Callable
from typing import TYPE_CHECKING, Any

from agent_framework import Agent, AgentSession
from tac.session import ThreadSafeSessionManager
from tac.channels.sms import SMSChannel, SMSChannelConfig
from tac.channels.voice import VoiceChannel, VoiceChannelConfig
from tac.core.logging import get_logger
from tac.models.session import ConversationSession

from .types import InMemoryAgentSessionStore, AgentSessionStore
from .utils import format_memory_context

if TYPE_CHECKING:
    from tac.models.tac import TACMemoryResponse

logger = get_logger(__name__)


class AgentFrameworkConnector:
    """
    Bridge for Twilio channels (Voice and SMS) with Agent Framework agents.

    Both voice and SMS flows are fully managed internally.  The developer
    supplies a ``create_agent`` factory and, optionally, hooks for message
    augmentation and error handling.  HTTP/WebSocket routing is handled
    by ``TACFastAPIServer`` — pass ``voice_channel`` and/or ``sms_channel`` to it
    to control which channels are active.

    Conversation history is managed via Agent Framework's ``AgentSession``.
    For voice, the agent and session persist in-memory for the duration of
    the WebSocket call, with background saves to the ``AgentSessionStore`` after
    each utterance for persistence/auditing.  For SMS, the session is loaded
    from and saved to the ``AgentSessionStore`` on every message.

    Lifecycle callbacks (``on_conversation_ended``, ``on_interrupt``) are
    wired automatically to handle voice agent cleanup and logging.

    Args:
        tac: TAC instance.
        create_agent: ``(session: ConversationSession) -> Agent``.
        on_message: Optional hook called before ``agent.run()`` for both
            voice and SMS.
            Signature: ``(user_message, context, memory_response) -> str``.
            When *None*, defaults to ``format_memory_context(memory, msg)``.
        on_error: Optional hook to customize error responses.
            Signature: ``(error, context) -> str``.
            When *None*, returns a default apology message.
        voice_config: Optional Voice channel configuration
            (``VoiceChannelConfig`` or dict).  Controls auto memory
            retrieval, session manager, etc.
        sms_config: Optional SMS channel configuration
            (``SMSChannelConfig`` or dict).  Controls auto memory
            retrieval, deduplication capacity, etc.
        session_store: Persistence layer for ``AgentSession`` objects.
            Used for SMS session continuity across messages and for
            background persistence of voice sessions (auditing, Foundry
            thread IDs).  Defaults to ``InMemoryAgentSessionStore`` (suitable
            for single-instance deployments).  For horizontal scaling,
            provide a persistent implementation (Redis, CosmosDB, etc.).
    """

    def __init__(
        self,
        tac: Any,
        create_agent: Callable[[ConversationSession], Agent],
        on_message: (
            Callable[
                [str, ConversationSession, TACMemoryResponse | None],
                str,
            ]
            | None
        ) = None,
        on_error: (
            Callable[[Exception, ConversationSession], str] | None
        ) = None,
        voice_config: VoiceChannelConfig | dict[str, Any] | None = None,
        sms_config: SMSChannelConfig | dict[str, Any] | None = None,
        session_store: AgentSessionStore | None = None,
    ):
        self.tac = tac
        self.create_agent = create_agent
        self.on_message = on_message
        self.on_error = on_error
        self.session_store: AgentSessionStore = (
            session_store if session_store is not None else InMemoryAgentSessionStore()
        )

        # -- Voice channel ----------------------------------------------------
        self._voice_agents: dict[str, Agent] = {}
        self._voice_sessions: dict[str, AgentSession] = {}
        self._session_manager = ThreadSafeSessionManager()

        # Merge session_manager into voice config
        if isinstance(voice_config, dict):
            voice_config = VoiceChannelConfig(
                session_manager=self._session_manager, **voice_config
            )
        elif voice_config is not None:
            voice_config = voice_config.model_copy(
                update={"session_manager": self._session_manager}
            )
        else:
            voice_config = VoiceChannelConfig(
                session_manager=self._session_manager
            )

        self.voice_channel = VoiceChannel(tac=self.tac, config=voice_config)

        # -- SMS channel ------------------------------------------------------
        self.sms_channel = SMSChannel(tac=self.tac, config=sms_config)

        # -- TAC callbacks ----------------------------------------------------
        self.tac.on_message_ready(self._handle_message)
        self.tac.on_conversation_ended(self._handle_conversation_ended)
        self.tac.on_interrupt(self._handle_interrupt)

        logger.info("AgentFrameworkConnector initialized")

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
    # Lifecycle callbacks
    # -------------------------------------------------------------------------

    async def _handle_conversation_ended(
        self,
        context: ConversationSession,
    ) -> None:
        """Clean up voice resources when a conversation ends."""
        if context.channel == "voice":
            self._cleanup_voice_agent(context.conversation_id)

    async def _handle_interrupt(
        self,
        context: ConversationSession,
        interrupt_data: Any,
    ) -> None:
        """Handle voice interrupt.

        Stream cancellation is handled automatically by the
        ``ThreadSafeSessionManager``.  This hook provides logging
        and a place for subclasses to add custom behavior.
        """
        logger.info(
            "Voice interrupted",
            conversation_id=context.conversation_id,
        )

    # -------------------------------------------------------------------------
    # Message building and error handling
    # -------------------------------------------------------------------------

    def _build_message(
        self,
        user_message: str,
        context: ConversationSession,
        memory_response: TACMemoryResponse | None,
    ) -> str:
        """Build the message to send to the agent.

        When ``on_message`` is set, delegates entirely to the hook.
        Otherwise, prepends memory context to the user message.
        Applied to both voice and SMS.
        """
        if self.on_message is not None:
            return self.on_message(user_message, context, memory_response)
        return format_memory_context(memory_response, user_message)

    def _get_error_response(
        self, error: Exception, context: ConversationSession
    ) -> str:
        """Get error response message.

        Uses ``on_error`` hook if set, otherwise returns a default message.
        """
        if self.on_error is not None:
            try:
                return self.on_error(error, context)
            except Exception:
                logger.error("on_error hook failed", exc_info=True)
        return "Sorry, something went wrong. Please try again."

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
        await self.voice_channel.send_response(
            context.conversation_id,
            self._stream_response(user_message, context, memory_response),
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

        message = self._build_message(user_message, context, memory_response)

        # Restore session from store (preserves Foundry thread_id,
        # message history, etc.) or create a fresh one.
        af_session = await self.session_store.load(context.conversation_id)
        if af_session is None:
            af_session = AgentSession(session_id=context.conversation_id)

        try:
            agent = self.create_agent(context)
            result = await agent.run(message, session=af_session)
            await self.sms_channel.send_response(
                context.conversation_id, result.text, role="assistant"
            )
        except Exception as e:
            logger.error(
                "Error processing SMS message",
                conversation_id=context.conversation_id,
                channel="sms",
                exc_info=True,
            )
            await self.sms_channel.send_response(
                context.conversation_id,
                self._get_error_response(e, context),
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
        self,
        user_message: str,
        context: ConversationSession,
        memory_response: TACMemoryResponse | None,
    ) -> AsyncGenerator[str, None]:
        """Stream generator that yields Agent Framework streaming responses.

        Integrates Agent Framework with TAC's streaming interface.
        Creates agent lazily on first call, reuses for subsequent utterances
        in the same call, and marks for cleanup when done.

        The same AgentSession is passed on every utterance so conversation
        history accumulates within the call.

        Yields:
            Text chunks from the agent streaming response (plain strings)
        """
        conv_id = context.conversation_id
        message = self._build_message(user_message, context, memory_response)

        prompt_preview = message[:100] + "..." if len(message) > 100 else message
        logger.info(
            f"USER MESSAGE | {prompt_preview}",
            conversation_id=conv_id,
            channel="voice",
        )

        agent = self._get_or_create_voice_agent(conv_id, context)
        af_session = self._get_or_create_voice_session(conv_id)

        full_response: list[str] = []

        try:
            async for chunk in agent.run(message, stream=True, session=af_session):
                if hasattr(chunk, "text") and chunk.text:
                    full_response.append(chunk.text)
                    yield chunk.text

            response_text = "".join(full_response)
            response_preview = (
                response_text[:100] + "..." if len(response_text) > 100 else response_text
            )
            logger.info(
                f"AI RESPONSE | {response_preview}",
                conversation_id=conv_id,
                channel="voice",
            )

            # Persist session in the background (non-blocking) for
            # auditing and Foundry thread_id durability.
            self._background_save_session(conv_id, af_session)
        except GeneratorExit:
            logger.info("Stream interrupted", conversation_id=conv_id)
            raise
        except Exception as e:
            logger.error(
                "Error during streaming",
                conversation_id=conv_id,
                exc_info=True,
                error=str(e),
            )
            self._cleanup_voice_agent(conv_id)
            yield self._get_error_response(e, context)

    def _get_or_create_voice_agent(
        self, conversation_id: str, context: ConversationSession
    ) -> Agent:
        """Get existing voice agent or create new one for conversation."""
        if conversation_id not in self._voice_agents:
            logger.info("Creating new voice agent", conversation_id=conversation_id)
            self._voice_agents[conversation_id] = self.create_agent(context)
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
        else:
            logger.warning(
                "No voice agent found to cleanup", conversation_id=conversation_id
            )
        if af_session:
            # Final persist to session store before discarding.
            self._background_save_session(conversation_id, af_session)
