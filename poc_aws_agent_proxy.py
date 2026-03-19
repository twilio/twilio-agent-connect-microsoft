"""
POC: tac_aws partner package — AgentProxy pattern.

Single OmniChannelHandler that works with any AgentProxy implementation.
The bridge handles TAC channel wiring; the proxy handles agent invocation.

    proxy = StrandsAgentProxy(agent)
    proxy = BedrockAgentProxy(client, agent_id, agent_alias_id, session_id)
    proxy = AgentCoreProxy(client, agent_runtime_arn, session_id)

    bridge = OmniChannelHandler(tac=tac, create_agent=factory)
    server = TACServer(tac=tac, voice_channel=bridge.voice_channel,
                       sms_channel=bridge.sms_channel)
    server.start()
"""

from __future__ import annotations

import asyncio
import uuid
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator, Callable
from typing import Any

from tac.channels.sms import SMSChannel
from tac.channels.voice import VoiceChannel
from tac.core.logging import get_logger
from tac.models.session import ConversationSession
from tac.models.tac import TACMemoryResponse
from tac.session import ThreadSafeSessionManager

logger = get_logger(__name__)


# ===========================================================================
# AgentProxy — abstract interface for all agent types
# ===========================================================================


class AgentProxy(ABC):
    """Abstract interface that normalizes agent invocation across frameworks.

    Every proxy exposes the same two methods regardless of whether the
    underlying agent is local (Strands), a managed API (Bedrock Agents),
    or a hosted runtime (AgentCore).
    """

    @abstractmethod
    async def run_async(self, prompt: str) -> str:
        """Invoke the agent and return the full response text."""
        ...

    @abstractmethod
    async def stream_async(self, prompt: str) -> AsyncGenerator[str, None]:
        """Invoke the agent and yield response text chunks."""
        ...

    def cleanup(self) -> None:
        """Optional cleanup hook. Override if the agent holds resources."""
        pass


# ===========================================================================
# Helpers
# ===========================================================================


async def _stream_from_sync_iterator(
    invoke_fn: Callable[[], Any],
    extract_chunks: Callable[[Any], Any],
) -> AsyncGenerator[str, None]:
    """Run a sync boto3 call in a thread and stream chunks back via queue.

    1. invoke_fn() runs in an executor to get the response.
    2. extract_chunks(response) is a sync iterator of text strings,
       consumed in a second executor thread.
    3. Chunks are pushed through an asyncio.Queue for async consumption.
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


# ===========================================================================
# 1. StrandsAgentProxy — wraps a local Strands Agent
# ===========================================================================


class StrandsAgentProxy(AgentProxy):
    """Proxy for a local Strands SDK agent.

    Args:
        agent: A strands.Agent instance.
    """

    def __init__(self, agent: Any):  # agent: strands.Agent
        self.agent = agent

    async def run_async(self, prompt: str) -> str:
        """Collect streaming response into full text."""
        chunks: list[str] = []
        async for chunk in self.stream_async(prompt):
            chunks.append(chunk)
        return "".join(chunks)

    async def stream_async(self, prompt: str) -> AsyncGenerator[str, None]:
        """Stream via Strands' native async generator.

        Strands events come as either:
            {"data": "text chunk"}
        or:
            {"event": {"contentBlockDelta": {"delta": {"text": "chunk"}}}}
        """
        async for event in self.agent.stream_async(prompt):
            if "data" in event:
                yield event["data"]
            elif "event" in event and "contentBlockDelta" in event["event"]:
                text = event["event"]["contentBlockDelta"]["delta"].get("text")
                if text:
                    yield text

    def cleanup(self) -> None:
        if hasattr(self.agent, "cleanup"):
            self.agent.cleanup()


# ===========================================================================
# 2. BedrockAgentProxy — invokes a managed Bedrock Agent via boto3
# ===========================================================================


class BedrockAgentProxy(AgentProxy):
    """Proxy for a managed Amazon Bedrock Agent.

    Invokes the agent via boto3 bedrock-agent-runtime client.
    Session continuity is handled by Bedrock's sessionId.

    Args:
        client: boto3 bedrock-agent-runtime client.
        agent_id: Bedrock agent ID.
        agent_alias_id: Bedrock agent alias ID.
        session_id: Session ID for conversation continuity.
    """

    def __init__(
        self,
        client: Any,
        agent_id: str,
        agent_alias_id: str,
        session_id: str,
    ):
        self.client = client
        self.agent_id = agent_id
        self.agent_alias_id = agent_alias_id
        self.session_id = session_id

    def _invoke(self, prompt: str, stream: bool = False) -> Any:
        """Sync boto3 invoke_agent call."""
        kwargs: dict[str, Any] = {
            "agentId": self.agent_id,
            "agentAliasId": self.agent_alias_id,
            "sessionId": self.session_id,
            "inputText": prompt,
        }
        if stream:
            kwargs["streamingConfigurations"] = {"streamFinalResponse": True}
        return self.client.invoke_agent(**kwargs)

    @staticmethod
    def _extract_chunks(response: Any):
        """Extract text from Bedrock EventStream (sync iterator)."""
        for event in response.get("completion", []):
            if "chunk" in event:
                chunk_bytes = event["chunk"].get("bytes", b"")
                text = chunk_bytes.decode("utf-8") if chunk_bytes else ""
                if text:
                    yield text

    async def run_async(self, prompt: str) -> str:
        chunks: list[str] = []
        async for chunk in self.stream_async(prompt):
            chunks.append(chunk)
        return "".join(chunks)

    async def stream_async(self, prompt: str) -> AsyncGenerator[str, None]:
        """Stream Bedrock Agent response.

        Both the API call and EventStream iteration run in executor
        threads so the event loop is never blocked.
        """
        async for chunk in _stream_from_sync_iterator(
            invoke_fn=lambda: self._invoke(prompt, stream=True),
            extract_chunks=self._extract_chunks,
        ):
            yield chunk


# ===========================================================================
# 3. AgentCoreProxy — invokes an agent hosted on AgentCore Runtime
# ===========================================================================


class AgentCoreProxy(AgentProxy):
    """Proxy for an agent hosted on Amazon Bedrock AgentCore Runtime.

    Invokes the agent via boto3 bedrock-agentcore-runtime client.

    Args:
        client: boto3 bedrock-agentcore-runtime client.
        agent_runtime_arn: ARN of the deployed AgentCore runtime.
        session_id: Session ID for conversation continuity.
    """

    def __init__(
        self,
        client: Any,
        agent_runtime_arn: str,
        session_id: str,
    ):
        self.client = client
        self.agent_runtime_arn = agent_runtime_arn
        self.session_id = session_id

    def _invoke(self, prompt: str) -> Any:
        """Sync boto3 invoke_agent_runtime call."""
        return self.client.invoke_agent_runtime(
            agentRuntimeArn=self.agent_runtime_arn,
            runtimeSessionId=self.session_id,
            payload={"prompt": prompt},
            qualifier="DEFAULT",
        )

    @staticmethod
    def _extract_chunks(response: Any):
        """Extract text from AgentCore response (sync iterator)."""
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

    async def run_async(self, prompt: str) -> str:
        chunks: list[str] = []
        async for chunk in self.stream_async(prompt):
            chunks.append(chunk)
        return "".join(chunks)

    async def stream_async(self, prompt: str) -> AsyncGenerator[str, None]:
        """Stream AgentCore response.

        Both the API call and response iteration run in executor
        threads so the event loop is never blocked.
        """
        async for chunk in _stream_from_sync_iterator(
            invoke_fn=lambda: self._invoke(prompt),
            extract_chunks=self._extract_chunks,
        ):
            yield chunk


# ===========================================================================
# OmniChannelHandler — single bridge class, works with any AgentProxy
# ===========================================================================


class OmniChannelHandler:
    """Bridges TAC channels to any agent framework via AgentProxy.

    The bridge handles all TAC channel wiring (voice streaming, SMS
    request/response, agent caching). The create_agent factory returns
    an AgentProxy, which normalizes invocation differences.

    Args:
        tac: TAC instance.
        create_agent: Factory returning an AgentProxy per conversation.
            Signature: (session: ConversationSession) -> AgentProxy
        channels: Channels to enable. Defaults to ["voice", "sms"].
        public_domain: Required for voice — ngrok/public domain.
        welcome_greeting: Initial voice greeting.
        auto_retrieve_memory: Auto-retrieve TAC memory before callbacks.
        websocket_path: WebSocket path for TwiML generation.
    """

    def __init__(
        self,
        tac: Any,
        create_agent: Callable[[ConversationSession], AgentProxy],
        channels: list[str] | None = None,
        public_domain: str | None = None,
        welcome_greeting: str = "Hello! How can I help you today!",
        auto_retrieve_memory: bool = False,
        websocket_path: str = "/ws",
    ):
        self.tac = tac
        self.create_agent = create_agent
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

        # Voice agent cache (persists for call duration)
        self._voice_agents: dict[str, AgentProxy] = {}

        # Register unified callback
        self.tac.on_message_ready(self._handle_message)

        logger.info("OmniChannelHandler initialized", channels=self.channels)

    # -- Callback dispatch --

    async def _handle_message(
        self,
        user_message: str,
        context: ConversationSession,
        memory_response: TACMemoryResponse | None,
    ) -> None:
        if context.channel == "voice":
            await self._handle_voice(user_message, context)
        elif context.channel == "sms":
            await self._handle_sms(user_message, context, memory_response)

    # -- Voice --

    async def _handle_voice(
        self, user_message: str, context: ConversationSession
    ) -> None:
        if self.voice_channel is None:
            return
        await self.voice_channel.send_response(
            context.conversation_id,
            self._stream_response(user_message, context.conversation_id),
        )

    async def _stream_response(
        self, prompt: str, session_id: str
    ) -> AsyncGenerator[str, None]:
        """Stream agent response for voice via AgentProxy.stream_async()."""
        prompt_preview = prompt[:100] + "..." if len(prompt) > 100 else prompt
        logger.info(
            f"USER MESSAGE | {prompt_preview}",
            conversation_id=session_id,
            channel="voice",
        )

        agent = self._get_or_create_voice_agent(session_id)
        full_response: list[str] = []

        try:
            async for chunk in agent.stream_async(prompt):
                full_response.append(chunk)
                yield chunk

            response_text = "".join(full_response)
            logger.info(
                f"AI RESPONSE | {response_text[:100]}",
                conversation_id=session_id,
                channel="voice",
            )
        except GeneratorExit:
            logger.info("Stream interrupted", session_id=session_id)
            self._cleanup_voice_agent(session_id)
            raise
        except Exception:
            logger.error("Voice streaming error", session_id=session_id, exc_info=True)
            self._cleanup_voice_agent(session_id)
            raise

    def _get_or_create_voice_agent(self, conversation_id: str) -> AgentProxy:
        if conversation_id not in self._voice_agents:
            session = self.voice_channel._conversations[conversation_id]
            self._voice_agents[conversation_id] = self.create_agent(session)
            logger.info("Created voice agent", conversation_id=conversation_id)
        return self._voice_agents[conversation_id]

    def _cleanup_voice_agent(self, conversation_id: str) -> None:
        agent = self._voice_agents.pop(conversation_id, None)
        if agent:
            agent.cleanup()
            logger.info("Cleaned up voice agent", conversation_id=conversation_id)

    # -- SMS --

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
            response_text = await agent.run_async(user_message)
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
            agent.cleanup()

    # -- Public route handlers --

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
# Example usage
# ===========================================================================

if __name__ == "__main__":
    """
    All three agent types use the same OmniChannelHandler.
    The factory returns the appropriate AgentProxy.
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
    # def create_agent(session: ConversationSession) -> AgentProxy:
    #     agent = Agent(
    #         model=BedrockModel(model_id="anthropic.claude-sonnet-4-20250514-v1:0"),
    #         system_prompt="You are a helpful assistant.",
    #         tools=[...],
    #     )
    #     return StrandsAgentProxy(agent)
    #
    # bridge = OmniChannelHandler(
    #     tac=tac,
    #     create_agent=create_agent,
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
    # import boto3
    # from tac import TAC
    # from tac.server import TACServer
    #
    # tac = TAC()
    # bedrock_client = boto3.client("bedrock-agent-runtime", region_name="us-east-1")
    #
    # def create_agent(session: ConversationSession) -> AgentProxy:
    #     return BedrockAgentProxy(
    #         client=bedrock_client,
    #         agent_id="ABCDE12345",
    #         agent_alias_id="TSTALIASID",
    #         session_id=session.conversation_id,
    #     )
    #
    # bridge = OmniChannelHandler(
    #     tac=tac,
    #     create_agent=create_agent,
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
    # import boto3
    # from tac import TAC
    # from tac.server import TACServer
    #
    # tac = TAC()
    # agentcore_client = boto3.client("bedrock-agentcore-runtime", region_name="us-east-1")
    #
    # def create_agent(session: ConversationSession) -> AgentProxy:
    #     return AgentCoreProxy(
    #         client=agentcore_client,
    #         agent_runtime_arn="arn:aws:bedrock:us-east-1:123456:agent-runtime/xyz",
    #         session_id=session.conversation_id,
    #     )
    #
    # bridge = OmniChannelHandler( 
    #     tac=tac,
    #     create_agent=create_agent,
    #     public_domain="your-domain.ngrok.io",
    # )
    #
    # server = TACServer(
    #     tac=tac,
    #     voice_channel=bridge.voice_channel,
    #     sms_channel=bridge.sms_channel,
    # )
    # ~~OR~~
    # server = AgentCoreServer( # Later once we have TAC / AgentCore runtime compatibility
    #     tac=tac,
    #     voice_channel=bridge.voice_channel,
    #     sms_channel=bridge.sms_channel,
    # )
    #
    # server.start()
    # 
    #

    print("See commented examples above for usage patterns.")
