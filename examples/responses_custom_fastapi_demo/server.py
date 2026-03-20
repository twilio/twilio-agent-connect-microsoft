"""Owl Internet Voice + SMS Agent — using MultiChannelBridge with custom FastAPI routes.

This example uses MultiChannelBridge + TACServer but adds custom routes by
accessing ``server.app`` (the underlying FastAPI instance). This gives full
control over additional routes and middleware while TACServer handles the
standard Twilio routing.
"""

# Fix SSL certificate verification on macOS (must be before other imports)
import truststore

truststore.inject_into_ssl()

import logging
import os

from azure.identity.aio import DefaultAzureCredential
from dotenv import load_dotenv
from fastapi.responses import HTMLResponse
from tac import TAC, TACConfig
from tac.server import TACServer

from agent_framework.azure import AzureOpenAIResponsesClient
from tac_azure import ConversationSession, MultiChannelBridge
from tac_azure.tools import create_knowledge_tool, create_memory_recall_tool, fetch_knowledge_base_info

load_dotenv()

credential = DefaultAzureCredential()
client = AzureOpenAIResponsesClient(
    credential=credential,
    project_endpoint=os.environ["AZURE_AI_PROJECT_ENDPOINT"],
    deployment_name="gpt-4o",
)

VOICE_SYSTEM_PROMPT = """You are Owl Internet's customer service assistant on a phone call.
Keep responses clear, concise, and conversational.
Use plain text only — no markdown, no lists, no special formatting."""

SMS_SYSTEM_PROMPT = """You are Owl Internet's customer service assistant over SMS.
Keep responses concise and formatted for text messaging.
Use short paragraphs. Bullet points are OK."""


def look_up_outage_tool(zip_code: str) -> str:
    """Check if there is a recent internet outage in a specific zip code."""
    return f"No reported outages in {zip_code}. Service is operating normally."


tac = TAC(config=TACConfig.from_env())
knowledge_base_id = os.environ.get("TWILIO_TAC_KNOWLEDGE_BASE_ID")
kb_info = None


def create_agent(session: ConversationSession):
    prompt = VOICE_SYSTEM_PROMPT if session.channel == "voice" else SMS_SYSTEM_PROMPT

    tools = [create_memory_recall_tool(tac, session), look_up_outage_tool]
    if kb_info:
        tools.append(
            create_knowledge_tool(
                tac,
                knowledge_base_id=knowledge_base_id,
                description=kb_info.description,
                name=kb_info.name,
            )
        )

    return client.as_agent(
        name="OwlAgent",
        instructions=prompt,
        tools=tools,
    )


# ---------------------------------------------------------------------------
# Startup — async init (e.g., fetch KB metadata)
# ---------------------------------------------------------------------------


async def startup():
    global kb_info
    if knowledge_base_id:
        kb_info = await fetch_knowledge_base_info(tac, knowledge_base_id)


# ---------------------------------------------------------------------------
# Bridge + Server
# ---------------------------------------------------------------------------

bridge = MultiChannelBridge(
    tac=tac,
    create_agent=create_agent,
    auto_retrieve_memory=True,
)

server = TACServer(
    tac=tac,
    voice_channel=bridge.voice_channel,
    sms_channel=bridge.sms_channel,
    on_startup=startup,
)


# ---------------------------------------------------------------------------
# Custom routes — added via server.app (the FastAPI instance)
# ---------------------------------------------------------------------------


@server.app.get("/", response_class=HTMLResponse)
async def landing_page():
    return """
    <html>
      <head><title>Owl Internet Agent</title></head>
      <body>
        <h1>Owl Internet Customer Service</h1>
        <p>This agent handles voice and SMS via Twilio.</p>
        <ul>
          <li><a href="/health">Health check</a></li>
        </ul>
      </body>
    </html>
    """


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    server.start()
