"""
POC: tac_aws partner package — three AgentFrameworkConnector implementations.

Each bridge has the same external interface (voice_channel, sms_channel)
and plugs into TACServer identically. Internals differ per agent framework.

Usage (all three):
    bridge = StrandsBridge(tac=tac, create_agent=factory)
    bridge = BedrockAgentsBridge(tac=tac, agent_id="...", agent_alias_id="...")
    bridge = AgentCoreBridge(tac=tac, agent_runtime_arn="...", create_payload=factory)

    server = TACServer(
        tac=tac,
        voice_channel=bridge.voice_channel,
        sms_channel=bridge.sms_channel,
    )
    server.start()
"""

from __future__ import annotations

import asyncio
import uuid
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator, Callable
from typing import Any, Protocol

from tac.channels.sms import SMSChannel
from tac.channels.voice import VoiceChannel
from tac.core.logging import get_logger
from tac.models.session import ConversationSession
from tac.models.tac import TACMemoryResponse
from tac.session import ThreadSafeSessionManager

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _stream_from_sync_iterator(
    invoke_fn: Callable[[], Any],
    extract_chunks: Callable[[Any], Any],
) -> AsyncGenerator[str, None]:
    """Run a sync boto3 call in a thread and stream chunks back without
    blocking the event loop.

    1. invoke_fn() is called in an executor to get the response.
    2. extract_chunks(response) returns a sync iterator of text strings.
    3. That iterator is consumed in a second executor thread, pushing
       chunks through an asyncio.Queue so the caller can ``async for``.
    """
    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(None, invoke_fn)

    queue: asyncio.Queue[str | None] = asyncio.Queue()

    def _read_stream() -> None:
        try:
            for text in extract_chunks(response):
                if text:
                    asyncio.run_coroutine_threadsafe(queue.put(text), loop)
        finally:
            asyncio.run_coroutine_threadsafe(queue.put(None), loop)

    loop.run_in_executor(None, _read_stream)

    while True:
        chunk = await queue.get()
        if chunk is None:
            break
        yield chunk


# ---------------------------------------------------------------------------
# Common protocol — all bridges expose the same external interface
# ---------------------------------------------------------------------------


class BaseAgentFrameworkConnector(ABC):
    """Base class defining the shared external interface for all bridges.

    Every bridge:
    - Creates VoiceChannel and SMSChannel from TAC
    - Registers on tac.on_message_ready()
    - Exposes voice_channel / sms_channel for TACServer
    """

    def __init__(
        self,
        tac: Any,
        channels: list[str] | None = None,
        public_domain: str | None = None,
        welcome_greeting: str = "Hello! How can I help you today!",
        auto_retrieve_memory: bool = False,
        websocket_path: str = "/ws",
    ):
        self.tac = tac
        self.channels = channels or ["voice", "sms"]
        self.public_domain = public_domain
        self.welcome_greeting = welcome_greeting
        self.websocket_path = websocket_path

        if "voice" in self.channels and not self.public_domain:
            raise ValueError("public_domain is required when 'voice' is in channels.")

        # -- Voice channel --
        self.voice_channel: VoiceChannel | None = None
        if "voice" in self.channels:
            self.tac_session_manager = ThreadSafeSessionManager()
            self.voice_channel = VoiceChannel(
                tac=self.tac,
                session_manager=self.tac_session_manager,
                auto_retrieve_memory=auto_retrieve_memory,
            )

        # -- SMS channel --
        self.sms_channel: SMSChannel | None = None
        if "sms" in self.channels:
            self.sms_channel = SMSChannel(
                tac=self.tac,
                auto_retrieve_memory=auto_retrieve_memory,
            )

        # Register unified callback
        self.tac.on_message_ready(self._handle_message)

    async def _handle_message(
        self,
        user_message: str,
        context: ConversationSession,
        memory_response: TACMemoryResponse | None,
    ) -> None:
        if context.channel == "voice":
            await self._handle_voice(user_message, context, memory_response)
        elif context.channel == "sms":
            await self._handle_sms(user_message, context, memory_response)

    async def _handle_voice(
        self,
        user_message: str,
        context: ConversationSession,
        memory_response: TACMemoryResponse | None,
    ) -> None:
        if self.voice_channel is None:
            return
        await self.voice_channel.send_response(
            context.conversation_id,
            self._stream_response(user_message, context.conversation_id),
        )

    @abstractmethod
    async def _stream_response(
        self, prompt: str, session_id: str
    ) -> AsyncGenerator[str, None]:
        """Yield text chunks for voice streaming. Framework-specific."""
        ...

    @abstractmethod
    async def _handle_sms(
        self,
        user_message: str,
        context: ConversationSession,
        memory_response: TACMemoryResponse | None,
    ) -> None:
        """Handle SMS message. Framework-specific."""
        ...

    # -- Public route handlers (same across all bridges) --

    async def handle_twiml_request(
        self, from_number: str, to_number: str, call_sid: str
    ) -> str:
        if self.voice_channel is None:
            raise RuntimeError("Voice channel not enabled.")
        websocket_url = f"wss://{self.public_domain}{self.websocket_path}"
        callback_url = f"https://{self.public_domain}/conversation-relay-callback"
        return await self.voice_channel.handle_incoming_call(
            to_number=to_number.replace("client:", ""),
            from_number=from_number.replace("client:", ""),
            options={
                "websocket_url": websocket_url,
                "action_url": callback_url,
                "welcome_greeting": self.welcome_greeting,
            },
            call_sid=call_sid,
        )

    async def handle_websocket_connection(self, websocket: Any) -> None:
        if self.voice_channel is None:
            raise RuntimeError("Voice channel not enabled.")
        await self.voice_channel.handle_websocket(websocket)

    async def handle_sms_webhook(self, webhook_data: dict[str, Any]) -> None:
        if self.sms_channel is None:
            raise RuntimeError("SMS channel not enabled.")
        await self.sms_channel.process_webhook(webhook_data)


# ===========================================================================
# 1. StrandsBridge — Strands SDK (local agent execution)
# ===========================================================================


class StrandsBridge(BaseAgentFrameworkConnector):
    """Bridge for Strands SDK agents.

    Strands agents run locally. The bridge manages agent lifecycle,
    streaming via agent.stream_async(), and conversation history via
    Strands' built-in session/conversation managers.

    Args:
        tac: TAC instance.
        create_agent: Factory returning a Strands Agent per conversation.
            Signature: (session: ConversationSession) -> strands.Agent
    """

    def __init__(
        self,
        tac: Any,
        create_agent: Callable[[ConversationSession], Any],  # -> strands.Agent
        **kwargs: Any,
    ):
        super().__init__(tac=tac, **kwargs)
        self.create_agent = create_agent
        self._voice_agents: dict[str, Any] = {}  # conversation_id -> Agent

    async def _stream_response(
        self, prompt: str, session_id: str
    ) -> AsyncGenerator[str, None]:
        """Stream Strands agent response for voice.

        Strands streaming yields events with structure:
            {"event": {"contentBlockDelta": {"delta": {"text": "chunk"}}}}
        """
        agent = self._get_or_create_voice_agent(session_id)
        full_response: list[str] = []

        try:
            async for event in agent.stream_async(prompt):
                # Strands event format
                if "data" in event:
                    full_response.append(event["data"])
                    yield event["data"]
                elif "event" in event and "contentBlockDelta" in event["event"]:
                    text = event["event"]["contentBlockDelta"]["delta"].get("text")
                    if text:
                        full_response.append(text)
                        yield text

            logger.info(
                f"AI RESPONSE | {''.join(full_response)[:100]}",
                conversation_id=session_id,
            )
        except GeneratorExit:
            self._cleanup_voice_agent(session_id)
            raise
        except Exception:
            self._cleanup_voice_agent(session_id)
            raise

    async def _handle_sms(
        self,
        user_message: str,
        context: ConversationSession,
        memory_response: TACMemoryResponse | None,
    ) -> None:
        """SMS: create ephemeral agent, run, send response, cleanup."""
        assert self.sms_channel is not None

        agent = self.create_agent(context)
        try:
            # Strands sync invocation returns result with .message
            result = agent(user_message)
            response_text = self._extract_text(result)
            await self.sms_channel.send_response(
                context.conversation_id, response_text, role="assistant"
            )
        except Exception:
            logger.error("SMS error", exc_info=True)
            await self.sms_channel.send_response(
                context.conversation_id,
                "Sorry, something went wrong.",
                role="assistant",
            )
        finally:
            if hasattr(agent, "cleanup"):
                agent.cleanup()

    def _get_or_create_voice_agent(self, conversation_id: str) -> Any:
        if conversation_id not in self._voice_agents:
            session = self.voice_channel._conversations[conversation_id]
            self._voice_agents[conversation_id] = self.create_agent(session)
        return self._voice_agents[conversation_id]

    def _cleanup_voice_agent(self, conversation_id: str) -> None:
        agent = self._voice_agents.pop(conversation_id, None)
        if agent and hasattr(agent, "cleanup"):
            agent.cleanup()

    @staticmethod
    def _extract_text(result: Any) -> str:
        if hasattr(result, "message"):
            message = result.message
            if isinstance(message, dict):
                content = message.get("content", [])
                if isinstance(content, list):
                    return "".join(
                        block.get("text", "")
                        for block in content
                        if isinstance(block, dict) and "text" in block
                    )
                return str(content)
            return str(message)
        return str(result)


# ===========================================================================
# 2. BedrockAgentsBridge — Bedrock Agents (managed service via boto3)
# ===========================================================================


class BedrockAgentsBridge(BaseAgentFrameworkConnector):
    """Bridge for Amazon Bedrock Agents (managed service).

    Bedrock Agents are invoked via the boto3 bedrock-agent-runtime API.
    No local agent — the bridge calls invoke_agent() with the user's
    message and streams the response back.

    Session continuity is handled by Bedrock's sessionId parameter.

    Args:
        tac: TAC instance.
        agent_id: Bedrock agent ID.
        agent_alias_id: Bedrock agent alias ID.
        region_name: AWS region. Defaults to us-east-1.
    """

    def __init__(
        self,
        tac: Any,
        agent_id: str,
        agent_alias_id: str,
        region_name: str = "us-east-1",
        **kwargs: Any,
    ):
        super().__init__(tac=tac, **kwargs)
        self.agent_id = agent_id
        self.agent_alias_id = agent_alias_id

        import boto3

        self.client = boto3.client(
            "bedrock-agent-runtime", region_name=region_name
        )

        # Map conversation_id -> bedrock session_id for continuity
        self._sessions: dict[str, str] = {}

    def _get_session_id(self, conversation_id: str) -> str:
        """Get or create a Bedrock session ID for a conversation."""
        if conversation_id not in self._sessions:
            self._sessions[conversation_id] = str(uuid.uuid4())
        return self._sessions[conversation_id]

    def _invoke(self, session_id: str, prompt: str, stream: bool = False) -> Any:
        """Sync boto3 invoke_agent call (runs in executor)."""
        kwargs: dict[str, Any] = {
            "agentId": self.agent_id,
            "agentAliasId": self.agent_alias_id,
            "sessionId": session_id,
            "inputText": prompt,
        }
        if stream:
            kwargs["streamingConfigurations"] = {"streamFinalResponse": True}
        return self.client.invoke_agent(**kwargs)

    @staticmethod
    def _extract_chunks(response: Any):
        """Extract text chunks from Bedrock EventStream (sync iterator)."""
        for event in response.get("completion", []):
            if "chunk" in event:
                chunk_bytes = event["chunk"].get("bytes", b"")
                text = chunk_bytes.decode("utf-8") if chunk_bytes else ""
                if text:
                    yield text

    async def _stream_response(
        self, prompt: str, session_id: str
    ) -> AsyncGenerator[str, None]:
        """Stream Bedrock Agent response for voice.

        Both the invoke_agent call and the EventStream iteration run
        in executor threads so the event loop is never blocked.
        """
        bedrock_session = self._get_session_id(session_id)

        try:
            async for chunk in _stream_from_sync_iterator(
                invoke_fn=lambda: self._invoke(bedrock_session, prompt, stream=True),
                extract_chunks=self._extract_chunks,
            ):
                yield chunk
        except GeneratorExit:
            raise
        except Exception:
            logger.error("Bedrock streaming error", exc_info=True)
            raise

    async def _handle_sms(
        self,
        user_message: str,
        context: ConversationSession,
        memory_response: TACMemoryResponse | None,
    ) -> None:
        """SMS: invoke Bedrock Agent, collect full response, send."""
        assert self.sms_channel is not None

        bedrock_session = self._get_session_id(context.conversation_id)

        try:
            full_text: list[str] = []
            async for chunk in _stream_from_sync_iterator(
                invoke_fn=lambda: self._invoke(bedrock_session, user_message),
                extract_chunks=self._extract_chunks,
            ):
                full_text.append(chunk)

            await self.sms_channel.send_response(
                context.conversation_id,
                "".join(full_text),
                role="assistant",
            )
        except Exception:
            logger.error("Bedrock SMS error", exc_info=True)
            await self.sms_channel.send_response(
                context.conversation_id,
                "Sorry, something went wrong.",
                role="assistant",
            )


# ===========================================================================
# 3. AgentCoreBridge — Bedrock AgentCore Runtime (managed hosting)
# ===========================================================================


class AgentCoreBridge(BaseAgentFrameworkConnector):
    """Bridge for Amazon Bedrock AgentCore Runtime.

    AgentCore hosts agents as managed runtimes invoked via
    invoke_agent_runtime(). Similar to BedrockAgentsBridge but
    targets AgentCore's API rather than Bedrock Agents.

    Args:
        tac: TAC instance.
        agent_runtime_arn: ARN of the deployed AgentCore runtime.
        region_name: AWS region. Defaults to us-east-1.
    """

    def __init__(
        self,
        tac: Any,
        agent_runtime_arn: str,
        region_name: str = "us-east-1",
        **kwargs: Any,
    ):
        super().__init__(tac=tac, **kwargs)
        self.agent_runtime_arn = agent_runtime_arn

        import boto3

        self.client = boto3.client(
            "bedrock-agentcore-runtime", region_name=region_name
        )

        self._sessions: dict[str, str] = {}

    def _get_session_id(self, conversation_id: str) -> str:
        if conversation_id not in self._sessions:
            self._sessions[conversation_id] = str(uuid.uuid4())
        return self._sessions[conversation_id]

    def _invoke(self, session_id: str, prompt: str) -> Any:
        """Sync boto3 invoke_agent_runtime call (runs in executor)."""
        return self.client.invoke_agent_runtime(
            agentRuntimeArn=self.agent_runtime_arn,
            runtimeSessionId=session_id,
            payload={"prompt": prompt},
            qualifier="DEFAULT",
        )

    @staticmethod
    def _extract_chunks(response: Any):
        """Extract text chunks from AgentCore response (sync iterator)."""
        stream = response.get("stream", response.get("body", []))
        for chunk in stream:
            if isinstance(chunk, bytes):
                text = chunk.decode("utf-8")
            elif isinstance(chunk, dict):
                text = chunk.get("text", chunk.get("bytes", b"").decode("utf-8"))
            else:
                text = str(chunk)
            if text:
                yield text

    async def _stream_response(
        self, prompt: str, session_id: str
    ) -> AsyncGenerator[str, None]:
        """Stream AgentCore response for voice.

        Both the invoke call and the response iteration run in
        executor threads so the event loop is never blocked.
        """
        runtime_session = self._get_session_id(session_id)

        try:
            async for chunk in _stream_from_sync_iterator(
                invoke_fn=lambda: self._invoke(runtime_session, prompt),
                extract_chunks=self._extract_chunks,
            ):
                yield chunk
        except GeneratorExit:
            raise
        except Exception:
            logger.error("AgentCore streaming error", exc_info=True)
            raise

    async def _handle_sms(
        self,
        user_message: str,
        context: ConversationSession,
        memory_response: TACMemoryResponse | None,
    ) -> None:
        """SMS: invoke AgentCore runtime, collect response, send."""
        assert self.sms_channel is not None

        runtime_session = self._get_session_id(context.conversation_id)

        try:
            full_text: list[str] = []
            async for chunk in _stream_from_sync_iterator(
                invoke_fn=lambda: self._invoke(runtime_session, user_message),
                extract_chunks=self._extract_chunks,
            ):
                full_text.append(chunk)

            await self.sms_channel.send_response(
                context.conversation_id,
                "".join(full_text),
                role="assistant",
            )
        except Exception:
            logger.error("AgentCore SMS error", exc_info=True)
            await self.sms_channel.send_response(
                context.conversation_id,
                "Sorry, something went wrong.",
                role="assistant",
            )


# ===========================================================================
# Example usage
# ===========================================================================

if __name__ == "__main__":
    """
    All three bridges have the same external interface.
    Swap the bridge, everything else stays identical.
    """

    # -- Example 1: Strands SDK ------------------------------------------
    #
    # from tac import TAC
    # from tac.server import TACServer
    # from strands import Agent
    # from strands.models import BedrockModel
    #
    # tac = TAC()
    #
    # def create_strands_agent(session: ConversationSession):
    #     system_prompt = (
    #         VOICE_PROMPT if session.channel == "voice" else SMS_PROMPT
    #     )
    #     return Agent(
    #         model=BedrockModel(model_id="anthropic.claude-sonnet-4-20250514-v1:0"),
    #         system_prompt=system_prompt,
    #         tools=[...],
    #     )
    #
    # bridge = StrandsBridge(
    #     tac=tac,
    #     create_agent=create_strands_agent,
    #     public_domain="your-domain.ngrok.io",
    # )
    #
    # server = TACServer(
    #     tac=tac,
    #     voice_channel=bridge.voice_channel,
    #     sms_channel=bridge.sms_channel,
    # )
    # server.start()

    # -- Example 2: Bedrock Agents ----------------------------------------
    #
    # tac = TAC()
    #
    # bridge = BedrockAgentsBridge(
    #     tac=tac,
    #     agent_id="ABCDE12345",
    #     agent_alias_id="TSTALIASID",
    #     public_domain="your-domain.ngrok.io",
    # )
    #
    # server = TACServer(
    #     tac=tac,
    #     voice_channel=bridge.voice_channel,
    #     sms_channel=bridge.sms_channel,
    # )
    # server.start()

    # -- Example 3: AgentCore Runtime -------------------------------------
    #
    # tac = TAC()
    #
    # bridge = AgentCoreBridge(
    #     tac=tac,
    #     agent_runtime_arn="arn:aws:bedrock:us-east-1:123456:agent-runtime/xyz",
    #     public_domain="your-domain.ngrok.io",
    # )
    #
    # server = TACServer(
    #     tac=tac,
    #     voice_channel=bridge.voice_channel,
    #     sms_channel=bridge.sms_channel,
    # )
    # server.start()

    print("See commented examples above for usage patterns.")
