"""Type definitions for the Voice Live connector."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any


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
        tools: Tool list — accepts ``TACTool`` instances (from
            ``@function_tool`` or ``create_*_tool`` factories) and/or raw
            OpenAI function-tool dicts.  ``TACTool`` entries are
            automatically converted to dict definitions and their
            executors are registered in *tool_executors*.
        tool_executors: Map of tool name to async callable that executes
            the tool.  Auto-populated from any ``TACTool`` objects in
            *tools*; you only need to set this manually when using raw
            dict tool definitions.
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
    tools: list[Any] = field(default_factory=list)
    tool_executors: dict[str, Callable[..., Awaitable[Any]]] = field(default_factory=dict)
    modalities: list[str] = field(default_factory=lambda: ["text"])
    temperature: float | None = None
    max_response_output_tokens: int | str | None = None

    def __post_init__(self) -> None:
        """Resolve any TACTool objects in *tools* to dict definitions."""
        from tac.tools.base import TACTool

        resolved: list[dict[str, Any]] = []
        for tool in self.tools:
            if isinstance(tool, TACTool):
                resolved.append(tool.to_openai_format())
                self.tool_executors[tool.name] = tool.implementation
            else:
                resolved.append(tool)
        self.tools = resolved

    @property
    def ws_url(self) -> str:
        """Build the Voice Live WebSocket URL."""
        return (
            f"wss://{self.endpoint}/voice-live/realtime"
            f"?api-version={self.api_version}&model={self.model}"
        )
