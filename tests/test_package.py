"""Tests for package structure and public imports."""

from __future__ import annotations

import pytest


class TestPackageImports:
    """Public API surface of ``tac_microsoft``."""

    def test_import_tac_microsoft(self) -> None:
        import tac_microsoft

        assert tac_microsoft is not None

    def test_reexported_tac_core_symbols(self) -> None:
        """Core TAC symbols are re-exported at the package root."""
        from tac_microsoft import TAC, TACConfig

        assert TAC is not None
        assert TACConfig is not None

    def test_channel_configs_exported(self) -> None:
        from tac_microsoft import (
            ChatChannelConfig,
            RCSChannelConfig,
            SMSChannelConfig,
            VoiceChannelConfig,
            WhatsAppChannelConfig,
        )

        assert VoiceChannelConfig is not None
        assert SMSChannelConfig is not None
        assert ChatChannelConfig is not None
        assert RCSChannelConfig is not None
        assert WhatsAppChannelConfig is not None

    def test_twiml_and_outbound_types_exported(self) -> None:
        from tac_microsoft import (
            InitiateChatConversationOptions,
            InitiateConversationResult,
            InitiateMessagingConversationOptions,
            InitiateVoiceConversationOptions,
            InitiateVoiceConversationResult,
            TwiMLOptions,
            TwiMLRequest,
        )

        assert TwiMLOptions is not None
        assert TwiMLRequest is not None
        assert InitiateVoiceConversationOptions is not None
        assert InitiateVoiceConversationResult is not None
        assert InitiateMessagingConversationOptions is not None
        assert InitiateChatConversationOptions is not None
        assert InitiateConversationResult is not None

    def test_conversation_session_exported(self) -> None:
        from tac_microsoft import ConversationSession

        assert ConversationSession is not None

    def test_format_memory_context_exported(self) -> None:
        from tac_microsoft import format_memory_context

        assert callable(format_memory_context)

    def test_agent_framework_connector_lazy_loaded(self) -> None:
        from tac_microsoft import AgentFrameworkConnector

        assert AgentFrameworkConnector is not None

    def test_voice_live_connector_lazy_loaded(self) -> None:
        from tac_microsoft import (
            VoiceLiveConfig,
            VoiceLiveConnector,
            VoiceLiveError,
        )

        assert VoiceLiveConnector is not None
        assert VoiceLiveConfig is not None
        assert VoiceLiveError is not None

    def test_session_stores_lazy_loaded(self) -> None:
        from tac_microsoft import (
            AgentSessionStore,
            CosmosDBAgentSessionStore,
            FileAgentSessionStore,
            InMemoryAgentSessionStore,
        )

        assert AgentSessionStore is not None
        assert InMemoryAgentSessionStore is not None
        assert FileAgentSessionStore is not None
        assert CosmosDBAgentSessionStore is not None

    def test_tac_fastapi_server_lazy_loaded(self) -> None:
        from tac_microsoft import TACFastAPIServer

        assert TACFastAPIServer is not None

    def test_unknown_attr_raises(self) -> None:
        import tac_microsoft

        with pytest.raises(AttributeError):
            _ = tac_microsoft.DoesNotExist


class TestToolsModules:
    """Public tool factories."""

    def test_agent_framework_tools_imports(self) -> None:
        from tac_microsoft.agent_framework_tools import (
            create_handoff_tool,
            create_knowledge_tool,
            create_memory_tool,
            fetch_knowledge_base_info,
            interstitial_filler,
        )

        for symbol in (
            create_memory_tool,
            create_knowledge_tool,
            create_handoff_tool,
            fetch_knowledge_base_info,
            interstitial_filler,
        ):
            assert symbol is not None

    def test_voice_live_tools_imports(self) -> None:
        from tac_microsoft.voice_live_tools import (
            create_handoff_tool,
            create_knowledge_tool,
            create_memory_tool,
            fetch_knowledge_base_info,
        )

        for symbol in (
            create_memory_tool,
            create_knowledge_tool,
            create_handoff_tool,
            fetch_knowledge_base_info,
        ):
            assert symbol is not None

    def test_no_deprecated_tool_exports(self) -> None:
        """Old placeholder tools were dropped in the tool-alignment refactor."""
        from tac_microsoft import agent_framework_tools, voice_live_tools

        assert not hasattr(agent_framework_tools, "create_flex_escalation_tool")
        assert not hasattr(agent_framework_tools, "create_messaging_tool")
        assert not hasattr(agent_framework_tools, "create_memory_recall_tool")
        assert not hasattr(voice_live_tools, "create_flex_escalation_tool")
        assert not hasattr(voice_live_tools, "create_messaging_tool")
        assert not hasattr(voice_live_tools, "create_memory_recall_tool")
