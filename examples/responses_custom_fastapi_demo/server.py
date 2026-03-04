"""Owl Internet Voice + SMS Agent — using OmniChannelHandler with a custom FastAPI app.

This example is identical to responses_voice_sms_demo in functionality, but builds
the FastAPI application manually instead of relying on OmniChannelServer. This gives
full control over routes, middleware, and application lifecycle.
"""

# Fix SSL certificate verification on macOS (must be before other imports)
import truststore

truststore.inject_into_ssl()

import asyncio
import logging
import os
from contextlib import asynccontextmanager

import uvicorn
from azure.identity.aio import DefaultAzureCredential
from dotenv import load_dotenv
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import HTMLResponse, JSONResponse, Response
from tac import TAC, TACConfig

from agent_framework.azure import AzureOpenAIResponsesClient
from tac_azure import ConversationSession, OmniChannelHandler
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
# OmniChannelHandler — handles voice & SMS logic without owning the FastAPI app
# ---------------------------------------------------------------------------

handler = OmniChannelHandler(
    tac=tac,
    create_agent=create_agent,
    public_domain=os.environ["TWILIO_TAC_VOICE_PUBLIC_DOMAIN"],
    welcome_greeting="Hello! I'm your Owl Internet assistant. How can I help?",
    channels=["voice", "sms"],
)


# ---------------------------------------------------------------------------
# FastAPI application — fully developer-owned
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    global kb_info
    if knowledge_base_id:
        kb_info = await fetch_knowledge_base_info(tac, knowledge_base_id)
    yield


app = FastAPI(title="Owl Internet (Custom FastAPI)", lifespan=lifespan)


# -- Custom landing page (not available with OmniChannelServer) -------------


@app.get("/", response_class=HTMLResponse)
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


# -- Voice routes -----------------------------------------------------------


@app.post("/twiml")
async def post_twiml(request: Request) -> Response:
    form = await request.form()
    xml = await handler.handle_twiml_request(
        from_number=str(form["From"]),
        to_number=str(form["To"]),
        call_sid=str(form["CallSid"]),
    )
    return Response(content=xml, media_type="application/xml")


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await handler.handle_websocket_connection(websocket)


@app.post("/conversation-relay-callback")
async def conversation_relay_callback(request: Request) -> Response:
    assert handler.voice_channel is not None
    form_data = await request.form()
    payload_dict = {key: str(value) for key, value in form_data.items()}
    result = await handler.voice_channel.handle_conversation_relay_callback(payload_dict)
    if result is not None:
        return Response(content=result, media_type="text/xml")
    return Response(content="OK", media_type="text/plain")


# -- SMS route --------------------------------------------------------------


@app.post("/webhook")
async def post_sms(request: Request):
    webhook_data = await request.json()
    idempotency_token = request.headers.get("i-twilio-idempotency-token")

    async def _process():
        try:
            await handler.handle_sms_webhook(webhook_data, idempotency_token)
        except Exception:
            logging.getLogger(__name__).error("Webhook processing failed", exc_info=True)

    asyncio.create_task(_process())
    return JSONResponse(content={"status": "ok"})


# -- Health check -----------------------------------------------------------


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "server": "tac-azure (custom fastapi)",
        "channels": handler.channels,
    }


# ---------------------------------------------------------------------------
# Run with uvicorn directly
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
