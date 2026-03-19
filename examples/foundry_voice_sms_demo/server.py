"""Owl Internet Voice + SMS Agent — Azure AI Foundry Agent Service.

Uses AzureAIAgentClient which runs agents server-side with managed threads.
Supports hosted tools like code interpreter, Bing web search, and file search.

This is the recommended starting point for Azure Foundry users.
"""

# Fix SSL certificate verification on macOS (must be before other imports)
import truststore
truststore.inject_into_ssl()

import logging
import os

from agent_framework.azure import AzureAIAgentClient
from azure.identity.aio import DefaultAzureCredential
from dotenv import load_dotenv
from tac import TAC, TACConfig

from tac_azure import ConversationSession, OmniChannelServer, format_memory_context
from tac_azure.tools import create_knowledge_tool, create_memory_recall_tool, fetch_knowledge_base_info

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Azure AI client
# ---------------------------------------------------------------------------

credential = DefaultAzureCredential()
client = AzureAIAgentClient(
    credential=credential,
    project_endpoint=os.environ["AZURE_AI_PROJECT_ENDPOINT"],
    model_deployment_name=os.environ.get("AZURE_AI_MODEL_DEPLOYMENT_NAME", "gpt-4o"),
)

# ---------------------------------------------------------------------------
# System prompts — channel-aware
# ---------------------------------------------------------------------------

VOICE_SYSTEM_PROMPT = """You are Owl Internet's customer service assistant on a phone call.
Keep responses clear, concise, and conversational.
Use plain text only — no markdown, no lists, no special formatting."""

SMS_SYSTEM_PROMPT = """You are Owl Internet's customer service assistant over SMS.
Keep responses concise and formatted for text messaging.
Use short paragraphs. Bullet points are OK."""

# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


def look_up_outage_tool(zip_code: str) -> str:
    """Check if there is a recent internet outage in a specific zip code."""
    return f"No reported outages in {zip_code}. Service is operating normally."


# Optional Bing web search — a Foundry-specific hosted tool.
# Requires BING_CONNECTION_ID env var; gracefully skipped if not configured.
web_search_tool = None
try:
    web_search_tool = AzureAIAgentClient.get_web_search_tool()
    logger.info("Bing web search tool enabled")
except ValueError:
    logger.info("Bing web search tool not configured (set BING_CONNECTION_ID to enable)")

# ---------------------------------------------------------------------------
# TAC + knowledge base
# ---------------------------------------------------------------------------

tac = TAC(config=TACConfig.from_env())
knowledge_base_id = os.environ.get("TWILIO_TAC_KNOWLEDGE_BASE_ID")
kb_info = None

# ---------------------------------------------------------------------------
# Agent factory — called once per voice call, once per SMS message
# ---------------------------------------------------------------------------


def create_agent(session: ConversationSession):
    prompt = VOICE_SYSTEM_PROMPT if session.channel == "voice" else SMS_SYSTEM_PROMPT

    tools = [create_memory_recall_tool(tac, session), look_up_outage_tool]
    if kb_info:
        tools.append(create_knowledge_tool(
            tac, knowledge_base_id=knowledge_base_id,
            description=kb_info.description, name=kb_info.name,
        ))
    if web_search_tool:
        tools.append(web_search_tool)

    return client.as_agent(
        name="OwlAgent",
        instructions=prompt,
        tools=tools,
    )


# ---------------------------------------------------------------------------
# on_message hook (optional) — customize how SMS messages are augmented
# ---------------------------------------------------------------------------
# By default, auto-retrieved memory is prepended to the user message via
# format_memory_context(). Override this to add custom context, transform
# the message, or skip memory injection entirely.
#
# Signature: (user_message: str, context: ConversationSession,
#              memory_response: TACMemoryResponse | None) -> str
#
# The returned string is what gets passed to agent.run().
#
# To disable memory fetching entirely (saves latency), set
# auto_retrieve_memory=False on OmniChannelServer instead.
# memory_response will then always be None.


def on_message(user_message, context, memory_response):
    """Prepend the customer's phone number to every SMS for context."""
    prefix = f"[Customer: {context.from_number}]\n"
    return prefix + format_memory_context(memory_response, user_message)


# ---------------------------------------------------------------------------
# Startup — async init (e.g., fetch KB metadata)
# ---------------------------------------------------------------------------


async def startup():
    global kb_info
    if knowledge_base_id:
        kb_info = await fetch_knowledge_base_info(tac, knowledge_base_id)


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------

server = OmniChannelServer(
    tac=tac,
    create_agent=create_agent,
    public_domain=os.environ["TWILIO_TAC_VOICE_PUBLIC_DOMAIN"],
    welcome_greeting="Hello! I'm your Owl Internet assistant. How can I help?",
    channels=["voice", "sms"],
    auto_retrieve_memory=True,
    on_message=on_message,
    on_startup=startup,
)

if __name__ == "__main__":
    server.serve()
