"""Voice Live connector for TAC.

Connector logic for Azure AI Foundry Voice Live.  Parallel to
``AgentFrameworkConnector`` but uses Voice Live's WebSocket API for LLM
inference instead of Microsoft Agent Framework's ``agent.run()``.

Voice Live is used in text-only mode (``modalities: ["text"]``) because
Conversation Relay handles STT/TTS.  The connector sends text in and
streams text deltas back.

Key design:
- ``VoiceLiveConfig`` holds connection parameters, instructions, tools,
  and tool executors
- A ``voice_channel`` instance is exposed — pass it to ``TACFastAPIServer``

Conversation history:
- A single ``VoiceLiveSession`` (WebSocket) is kept open for the
  duration of the call.  Voice Live manages conversation state
  server-side, so all utterances within a call share context.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Callable
from typing import TYPE_CHECKING, Any

from tac.session import ThreadSafeSessionManager
from tac.channels.voice import VoiceChannel, VoiceChannelConfig
from tac.core.logging import get_logger
from tac.models.session import ConversationSession

from .utils import format_memory_context
from .voice_live_session import VoiceLiveSession
from .voice_live_types import VoiceLiveConfig

if TYPE_CHECKING:
    from tac.models.tac import TACMemoryResponse

logger = get_logger(__name__)


class VoiceLiveConnector:
    """Connector for Twilio voice using Azure Voice Live for LLM inference.

    Parallel to ``AgentFrameworkConnector`` but uses Voice Live's WebSocket
    API instead of Agent Framework.  Voice Live manages conversation state
    server-side, so no ``AgentSession`` or session store is needed.

    This connector is voice-only.  For SMS/messaging, use
    ``AgentFrameworkConnector`` or a separate connector.

    Args:
        tac: TAC instance.
        config: ``VoiceLiveConfig`` with endpoint, auth, instructions, tools.
        on_message: Optional hook called before sending to Voice Live.
            Signature: ``(user_message, context, memory_response) -> str``.
            When *None*, defaults to ``format_memory_context(memory, msg)``.
        on_error: Optional hook to customize error responses.
            Signature: ``(error, context) -> str``.
        auto_retrieve_memory: If *True*, TAC voice channel auto-retrieves
            memory before invoking callbacks.
    """

    def __init__(
        self,
        tac: Any,
        config: VoiceLiveConfig,
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
        auto_retrieve_memory: bool = False,
    ):
        self.tac = tac
        self.config = config
        self.on_message = on_message
        self.on_error = on_error

        # Per-conversation Voice Live sessions
        self._voice_sessions: dict[str, VoiceLiveSession] = {}

        # -- Voice channel ----------------------------------------------------
        self._session_manager = ThreadSafeSessionManager()
        self.voice_channel = VoiceChannel(
            tac=self.tac,
            config=VoiceChannelConfig(
                session_manager=self._session_manager,
                auto_retrieve_memory=auto_retrieve_memory,
            ),
        )

        # -- TAC callbacks ----------------------------------------------------
        self.tac.on_message_ready(self._handle_message)
        self.tac.on_conversation_ended(self._handle_conversation_ended)
        self.tac.on_interrupt(self._handle_interrupt)

        logger.info("VoiceLiveConnector initialized")

    # ------------------------------------------------------------------
    # Message callback
    # ------------------------------------------------------------------

    async def _handle_message(
        self,
        user_message: str,
        context: ConversationSession,
        memory_response: TACMemoryResponse | None,
    ) -> None:
        """Callback registered with ``tac.on_message_ready()``."""
        if context.channel == "voice":
            await self._handle_voice_message(user_message, context, memory_response)
        else:
            logger.warning(
                "VoiceLiveConnector received non-voice message, ignoring",
                channel=context.channel,
                conversation_id=context.conversation_id,
            )

    # ------------------------------------------------------------------
    # Lifecycle callbacks
    # ------------------------------------------------------------------

    async def _handle_conversation_ended(
        self, context: ConversationSession
    ) -> None:
        """Close and clean up the Voice Live session when a call ends."""
        if context.channel == "voice":
            await self._cleanup_voice_session(context.conversation_id)

    async def _handle_interrupt(
        self,
        context: ConversationSession,
        interrupt_data: Any,
    ) -> None:
        """Cancel the in-progress Voice Live response on interrupt."""
        session = self._voice_sessions.get(context.conversation_id)
        if session:
            await session.cancel_response()
        logger.info(
            "Voice interrupted",
            conversation_id=context.conversation_id,
        )

    # ------------------------------------------------------------------
    # Message building and error handling
    # ------------------------------------------------------------------

    def _build_message(
        self,
        user_message: str,
        context: ConversationSession,
        memory_response: TACMemoryResponse | None,
    ) -> str:
        """Build the message to send to Voice Live.

        Delegates to ``on_message`` hook if set, otherwise prepends
        memory context to the user message.
        """
        if self.on_message is not None:
            return self.on_message(user_message, context, memory_response)
        return format_memory_context(memory_response, user_message)

    def _get_error_response(
        self, error: Exception, context: ConversationSession
    ) -> str:
        """Get error response message."""
        if self.on_error is not None:
            try:
                return self.on_error(error, context)
            except Exception:
                logger.error("on_error hook failed", exc_info=True)
        return "Sorry, something went wrong. Please try again."

    # ------------------------------------------------------------------
    # Voice handler
    # ------------------------------------------------------------------

    async def _handle_voice_message(
        self,
        user_message: str,
        context: ConversationSession,
        memory_response: TACMemoryResponse | None,
    ) -> None:
        """Stream the Voice Live response through the voice channel."""
        await self.voice_channel.send_response(
            context.conversation_id,
            self._stream_response(user_message, context, memory_response),
        )

    async def _stream_response(
        self,
        user_message: str,
        context: ConversationSession,
        memory_response: TACMemoryResponse | None,
    ) -> AsyncGenerator[str, None]:
        """Yield streaming text chunks from Voice Live.

        Creates the ``VoiceLiveSession`` lazily on the first utterance
        and reuses it for subsequent utterances within the same call.
        """
        conv_id = context.conversation_id
        message = self._build_message(user_message, context, memory_response)

        prompt_preview = message[:100] + "..." if len(message) > 100 else message
        logger.info(
            f"USER MESSAGE | {prompt_preview}",
            conversation_id=conv_id,
            channel="voice",
        )

        session = await self._get_or_create_voice_session(conv_id)
        full_response: list[str] = []

        try:
            async for chunk in session.send_message_and_stream(message):
                full_response.append(chunk)
                yield chunk

            response_text = "".join(full_response)
            response_preview = (
                response_text[:100] + "..." if len(response_text) > 100 else response_text
            )
            logger.info(
                f"AI RESPONSE | {response_preview}",
                conversation_id=conv_id,
                channel="voice",
            )
        except GeneratorExit:
            logger.info("Stream interrupted", conversation_id=conv_id)
            raise
        except Exception as e:
            logger.error(
                "Error during Voice Live streaming",
                conversation_id=conv_id,
                exc_info=True,
                error=str(e),
            )
            await self._cleanup_voice_session(conv_id)
            yield self._get_error_response(e, context)

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    async def _get_or_create_voice_session(
        self, conversation_id: str
    ) -> VoiceLiveSession:
        """Get an existing session or create and configure a new one."""
        if conversation_id not in self._voice_sessions:
            logger.info(
                "Creating new Voice Live session",
                conversation_id=conversation_id,
            )
            session = VoiceLiveSession(self.config, conversation_id)
            await session.connect()
            await session.configure()
            self._voice_sessions[conversation_id] = session
        return self._voice_sessions[conversation_id]

    async def _cleanup_voice_session(self, conversation_id: str) -> None:
        """Close and remove the Voice Live session for a conversation."""
        session = self._voice_sessions.pop(conversation_id, None)
        if session:
            await session.close()
            logger.info(
                "Cleaned up Voice Live session",
                conversation_id=conversation_id,
            )
        else:
            logger.warning(
                "No Voice Live session found to cleanup",
                conversation_id=conversation_id,
            )
