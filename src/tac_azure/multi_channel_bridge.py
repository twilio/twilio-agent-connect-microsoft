"""
MultiChannel Bridge for Agent Framework + TAC

Bridge logic (agent lifecycle, session management, tool factories) for Microsoft
Agent Framework.  HTTP/WebSocket routing is delegated to ``TACServer`` from the
``tac`` package.

Key design:
- ``create_agent`` factory returns an Agent Framework ``Agent``
- Voice and SMS channel instances are exposed as ``voice_channel`` / ``sms_channel``
  — pass whichever you need to ``TACServer`` to wire up routing

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
from tac.channels.sms import SMSChannel
from tac.channels.voice import VoiceChannel
from tac.core.logging import get_logger
from tac.models.session import ConversationSession

from .types import InMemoryAgentSessionStore, AgentSessionStore
from .utils import format_memory_context

if TYPE_CHECKING:
    from tac.models.tac import TACMemoryResponse

logger = get_logger(__name__)


class MultiChannelBridge:
    """
    Bridge for Twilio channels (Voice and SMS) with Agent Framework agents.

    Both voice and SMS flows are fully managed internally.  The developer
    supplies a ``create_agent`` factory and, optionally, an ``on_message``
    hook for SMS message augmentation.  HTTP/WebSocket routing is handled
    by ``TACServer`` — pass ``voice_channel`` and/or ``sms_channel`` to it
    to control which channels are active.

    Conversation history is managed via Agent Framework's ``AgentSession``.
    For voice, the agent and session persist in-memory for the duration of
    the WebSocket call, with background saves to the ``AgentSessionStore`` after
    each utterance for persistence/auditing.  For SMS, the session is loaded
    from and saved to the ``AgentSessionStore`` on every message.

    Args:
        tac: TAC instance.
        create_agent: ``(session: ConversationSession) -> Agent``.
        on_message: Optional hook called before ``agent.run()`` for SMS.
            Signature: ``(user_message, context, memory_response) -> str``.
            When *None*, defaults to ``format_memory_context(memory, msg)``.
        auto_retrieve_memory: If *True*, TAC channels auto-retrieve
            memory before invoking callbacks.  Defaults to *False*.
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
        auto_retrieve_memory: bool = False,
        session_store: AgentSessionStore | None = None,
    ):
        self.tac = tac
        self.create_agent = create_agent
        self.on_message = on_message
        self.session_store: AgentSessionStore = (
            session_store if session_store is not None else InMemoryAgentSessionStore()
        )

        # -- Voice channel ----------------------------------------------------
        self._voice_agents: dict[str, Agent] = {}
        self._voice_sessions: dict[str, AgentSession] = {}
        self.tac_session_manager = ThreadSafeSessionManager()
        self.voice_channel = VoiceChannel(
            tac=self.tac,
            session_manager=self.tac_session_manager,
            auto_retrieve_memory=auto_retrieve_memory,
        )

        # -- SMS channel ------------------------------------------------------
        self.sms_channel = SMSChannel(
            tac=self.tac,
            auto_retrieve_memory=auto_retrieve_memory,
        )

        # Register a single unified callback that dispatches by channel
        self.tac.on_message_ready(self._handle_message)

        logger.info("MultiChannelBridge initialized (Agent Framework)")

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

    def _get_or_create_voice_agent(self, conversation_id: str) -> Agent:
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
                raise RuntimeError(
                    "Cannot create agent: profile_id is not set for this conversation."
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
