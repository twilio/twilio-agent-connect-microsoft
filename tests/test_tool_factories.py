"""Tests for tool factory wiring.

These factories delegate to ``tac.tools`` — the tests verify wiring
(prerequisite checks, delegation) rather than the tool behavior itself,
which core TAC already covers.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from twilio_agent_connect_microsoft import agent_framework_tools, voice_live_tools
from twilio_agent_connect_microsoft._tool_factories import (
    create_handoff_tool,
    create_knowledge_tool,
    create_memory_tool,
    fetch_knowledge_base_info,
)


class TestCreateMemoryTool:
    """Wraps ``tac.tools.create_memory_tool``."""

    def test_returns_none_when_memory_client_missing(
        self, mock_tac: MagicMock, mock_sms_session: MagicMock
    ) -> None:
        mock_tac.conversation_memory_client = None

        assert create_memory_tool(mock_tac, mock_sms_session) is None

    def test_returns_none_when_profile_id_missing(
        self, mock_tac: MagicMock, mock_sms_session: MagicMock
    ) -> None:
        mock_sms_session.profile_id = None

        assert create_memory_tool(mock_tac, mock_sms_session) is None

    def test_delegates_to_core_with_client_and_session(
        self, mock_tac: MagicMock, mock_sms_session: MagicMock
    ) -> None:
        with patch(
            "twilio_agent_connect_microsoft._tool_factories._core_create_memory_tool"
        ) as core:
            core.return_value = MagicMock(name="tac_tool")

            result = create_memory_tool(mock_tac, mock_sms_session)

            core.assert_called_once_with(
                conversation_memory_client=mock_tac.conversation_memory_client,
                session=mock_sms_session,
                name=None,
                description=None,
            )
            assert result is core.return_value

    def test_forwards_name_and_description(
        self, mock_tac: MagicMock, mock_sms_session: MagicMock
    ) -> None:
        with patch(
            "twilio_agent_connect_microsoft._tool_factories._core_create_memory_tool"
        ) as core:
            create_memory_tool(
                mock_tac,
                mock_sms_session,
                name="recall_user",
                description="Recall user preferences.",
            )

            _, kwargs = core.call_args
            assert kwargs["name"] == "recall_user"
            assert kwargs["description"] == "Recall user preferences."


class TestCreateKnowledgeTool:
    """Wraps ``tac.tools.create_knowledge_tool`` (async)."""

    async def test_raises_when_knowledge_base_id_blank(self, mock_tac: MagicMock) -> None:
        with pytest.raises(ValueError, match="knowledge_base_id is required"):
            await create_knowledge_tool(mock_tac, "")

    async def test_raises_when_knowledge_client_missing(self, mock_tac: MagicMock) -> None:
        mock_tac.knowledge_client = None

        with pytest.raises(ValueError, match="knowledge_client is not initialised"):
            await create_knowledge_tool(mock_tac, "kb_123")

    async def test_delegates_to_core(self, mock_tac: MagicMock) -> None:
        with patch(
            "twilio_agent_connect_microsoft._tool_factories._core_create_knowledge_tool",
            new_callable=AsyncMock,
        ) as core:
            core.return_value = MagicMock(name="tac_tool")

            result = await create_knowledge_tool(
                mock_tac,
                "kb_123",
                name="search_faqs",
                description="Search FAQs",
                top_k=3,
            )

            core.assert_awaited_once_with(
                knowledge_client=mock_tac.knowledge_client,
                knowledge_base_id="kb_123",
                name="search_faqs",
                description="Search FAQs",
                top_k=3,
            )
            assert result is core.return_value


class TestCreateHandoffTool:
    """Wraps ``tac.tools.create_studio_handoff_tool``."""

    def test_delegates_to_core(self, mock_tac: MagicMock, mock_sms_session: MagicMock) -> None:
        with patch(
            "twilio_agent_connect_microsoft._tool_factories._core_create_studio_handoff_tool"
        ) as core:
            core.return_value = MagicMock(name="tac_tool")
            attributes = {"department": "billing"}

            result = create_handoff_tool(mock_tac, mock_sms_session, attributes)

            core.assert_called_once_with(mock_tac, mock_sms_session, attributes)
            assert result is core.return_value

    def test_passes_none_attributes_through(
        self, mock_tac: MagicMock, mock_sms_session: MagicMock
    ) -> None:
        with patch(
            "twilio_agent_connect_microsoft._tool_factories._core_create_studio_handoff_tool"
        ) as core:
            create_handoff_tool(mock_tac, mock_sms_session)

            core.assert_called_once_with(mock_tac, mock_sms_session, None)


class TestFetchKnowledgeBaseInfo:
    """Helper that reads display_name + description off a knowledge base."""

    async def test_raises_when_client_missing(self, mock_tac: MagicMock) -> None:
        mock_tac.knowledge_client = None

        with pytest.raises(ValueError, match="knowledge_client is not initialised"):
            await fetch_knowledge_base_info(mock_tac, "kb_123")

    async def test_returns_info_from_client(self, mock_tac: MagicMock) -> None:
        kb = MagicMock()
        kb.display_name = "Billing FAQs"
        kb.description = "Billing and invoice questions"
        mock_tac.knowledge_client.get_knowledge_base = AsyncMock(return_value=kb)

        info = await fetch_knowledge_base_info(mock_tac, "kb_123")

        assert info.name == "search_billing_faqs"
        assert info.description == "Billing and invoice questions"

    async def test_name_handles_dashes_and_case(self, mock_tac: MagicMock) -> None:
        kb = MagicMock()
        kb.display_name = "Customer-Support Docs"
        kb.description = "docs"
        mock_tac.knowledge_client.get_knowledge_base = AsyncMock(return_value=kb)

        info = await fetch_knowledge_base_info(mock_tac, "kb_123")

        assert info.name == "search_customer_support_docs"


class TestAgentFrameworkToolsAdapter:
    """``agent_framework_tools`` returns plain callables, not TACTool."""

    def test_memory_tool_returns_implementation(
        self, mock_tac: MagicMock, mock_sms_session: MagicMock
    ) -> None:
        tac_tool = MagicMock()
        tac_tool.implementation = MagicMock(name="plain_callable")

        with patch(
            "twilio_agent_connect_microsoft._tool_factories._core_create_memory_tool",
            return_value=tac_tool,
        ):
            result = agent_framework_tools.create_memory_tool(mock_tac, mock_sms_session)

        assert result is tac_tool.implementation

    def test_memory_tool_returns_none_when_prereqs_unmet(
        self, mock_tac: MagicMock, mock_sms_session: MagicMock
    ) -> None:
        mock_tac.conversation_memory_client = None

        assert agent_framework_tools.create_memory_tool(mock_tac, mock_sms_session) is None

    async def test_knowledge_tool_returns_implementation(self, mock_tac: MagicMock) -> None:
        tac_tool = MagicMock()
        tac_tool.implementation = MagicMock(name="plain_callable")

        with patch(
            "twilio_agent_connect_microsoft._tool_factories._core_create_knowledge_tool",
            new_callable=AsyncMock,
            return_value=tac_tool,
        ):
            result = await agent_framework_tools.create_knowledge_tool(mock_tac, "kb_123")

        assert result is tac_tool.implementation


class TestVoiceLiveToolsAdapter:
    """``voice_live_tools`` returns TACTool instances directly."""

    def test_memory_tool_returns_tac_tool(
        self, mock_tac: MagicMock, mock_sms_session: MagicMock
    ) -> None:
        tac_tool = MagicMock(name="tac_tool")

        with patch(
            "twilio_agent_connect_microsoft._tool_factories._core_create_memory_tool",
            return_value=tac_tool,
        ):
            result = voice_live_tools.create_memory_tool(mock_tac, mock_sms_session)

        assert result is tac_tool

    async def test_knowledge_tool_returns_tac_tool(self, mock_tac: MagicMock) -> None:
        tac_tool = MagicMock(name="tac_tool")

        with patch(
            "twilio_agent_connect_microsoft._tool_factories._core_create_knowledge_tool",
            new_callable=AsyncMock,
            return_value=tac_tool,
        ):
            result = await voice_live_tools.create_knowledge_tool(mock_tac, "kb_123")

        assert result is tac_tool
