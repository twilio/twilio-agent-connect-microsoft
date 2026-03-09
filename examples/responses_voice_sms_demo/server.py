"""Owl Internet Voice + SMS Agent — Azure OpenAI Responses API.

Uses AzureOpenAIResponsesClient (Chat Completions). Simpler setup than Foundry —
no managed threads, no hosted tools. Good starting point for Azure OpenAI users.
"""

# Fix SSL certificate verification on macOS (must be before other imports)
import truststore
truststore.inject_into_ssl()

import os

from agent_framework.azure import AzureOpenAIResponsesClient
from azure.identity.aio import DefaultAzureCredential
from dotenv import load_dotenv
from tac import TAC, TACConfig

from tac_azure import ConversationSession, OmniChannelServer
from tac_azure.tools import create_knowledge_tool, create_memory_recall_tool

load_dotenv()

# ---------------------------------------------------------------------------
# Azure AI client
# ---------------------------------------------------------------------------

credential = DefaultAzureCredential()
client = AzureOpenAIResponsesClient(
    credential=credential,
    project_endpoint=os.environ["AZURE_AI_PROJECT_ENDPOINT"],
    deployment_name="gpt-4o",
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


# ---------------------------------------------------------------------------
# TAC + knowledge base
# ---------------------------------------------------------------------------

tac = TAC(config=TACConfig.from_env())
knowledge_base_id = os.environ.get("TWILIO_TAC_KNOWLEDGE_BASE_ID")

# ---------------------------------------------------------------------------
# Agent factory — called once per voice call, once per SMS message
# ---------------------------------------------------------------------------


def create_agent(session: ConversationSession):
    prompt = VOICE_SYSTEM_PROMPT if session.channel == "voice" else SMS_SYSTEM_PROMPT

    tools = [create_memory_recall_tool(tac, session), look_up_outage_tool]
    if knowledge_base_id:
        tools.append(create_knowledge_tool(
            tac, knowledge_base_id=knowledge_base_id,
            description="Search for information about Twilio's Sierra initiative, including Memora "
            "(conversation memory service) and Maestro (orchestration service).",
        ))

    return client.as_agent(
        name="OwlAgent",
        instructions=prompt,
        tools=tools,
    )


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------

server = OmniChannelServer(
    tac=tac,
    create_agent=create_agent,
    public_domain=os.environ["TWILIO_TAC_VOICE_PUBLIC_DOMAIN"],
    welcome_greeting="Hello! I'm your Owl Internet assistant. How can I help?",
    channels=["voice", "sms"],
)

if __name__ == "__main__":
    server.serve()
