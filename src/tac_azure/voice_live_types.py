"""Type definitions for the Voice Live connector."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable


class VoiceLiveError(Exception):
    """Raised when a Voice Live API error occurs."""


@dataclass
class VoiceLiveConfig:
    """Configuration for connecting to Azure AI Foundry Voice Live.

    Voice Live is used in text-only mode (``modalities: ["text"]``) because
    Conversation Relay handles STT/TTS.  The connector sends text in and
    streams text deltas back.

    Args:
        endpoint: Azure resource hostname, e.g.
            ``"your-resource.services.ai.azure.com"``.
        model: Voice Live model name, e.g. ``"gpt-4o"``.
        api_key: API key for authentication (mutually exclusive with
            *credential*).
        credential: Azure identity credential for Entra token auth
            (mutually exclusive with *api_key*).
        api_version: Voice Live API version.
        instructions: System instructions for the model.
        tools: Tool definitions in OpenAI function-tool format.
        tool_executors: Map of tool name to async callable that executes
            the tool.  The callable receives keyword arguments matching the
            tool's parameters and must return a string result.
        modalities: Session modalities.  Defaults to ``["text"]``.
        temperature: Sampling temperature (0.6 – 1.2).
        max_response_output_tokens: Max output tokens per response.
    """

    # Connection
    endpoint: str
    model: str
    api_key: str | None = None
    credential: Any = None
    api_version: str = "2025-10-01"

    # Session configuration
    instructions: str = ""
    tools: list[dict[str, Any]] = field(default_factory=list)
    tool_executors: dict[str, Callable[..., Awaitable[str]]] = field(
        default_factory=dict
    )
    modalities: list[str] = field(default_factory=lambda: ["text"])
    temperature: float | None = None
    max_response_output_tokens: int | str | None = None

    @property
    def ws_url(self) -> str:
        """Build the Voice Live WebSocket URL."""
        return (
            f"wss://{self.endpoint}/voice-live/realtime"
            f"?api-version={self.api_version}&model={self.model}"
        )
