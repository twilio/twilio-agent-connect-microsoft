"""Owl Internet Voice Agent — Voice Live example.

Uses Azure AI Foundry Voice Live for LLM inference instead of
Microsoft Agent Framework.  Voice Live manages conversation state
server-side via its WebSocket API.

Voice Live is used in text-only mode because Conversation Relay
handles STT/TTS.  The connector sends text in and streams text
deltas back.
"""

# Fix SSL certificate verification on macOS (must be before other imports)
import truststore
truststore.inject_into_ssl()

import os

from dotenv import load_dotenv

from tac_azure import (
    TAC,
    TACConfig,
    TACFastAPIServer,
    VoiceLiveConnector,
    VoiceLiveConfig,
)

load_dotenv()


# ---------------------------------------------------------------------------
# Tool definitions (OpenAI function format)
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "look_up_outage",
            "description": "Check if there is a recent internet outage in a specific zip code.",
            "parameters": {
                "type": "object",
                "properties": {
                    "zip_code": {
                        "type": "string",
                        "description": "The zip code to check for outages.",
                    }
                },
                "required": ["zip_code"],
            },
        },
    }
]


# ---------------------------------------------------------------------------
# Tool executors
# ---------------------------------------------------------------------------

async def look_up_outage(zip_code: str) -> str:
    """Check for internet outages in a zip code."""
    return f"No reported outages in {zip_code}. Service is operating normally."


# ---------------------------------------------------------------------------
# TAC + Voice Live setup
# ---------------------------------------------------------------------------

tac = TAC(config=TACConfig.from_env())

config = VoiceLiveConfig(
    endpoint=os.environ["AZURE_VOICE_LIVE_ENDPOINT"],
    model=os.environ.get("AZURE_VOICE_LIVE_MODEL", "gpt-4o"),
    api_key=os.environ.get("AZURE_VOICE_LIVE_API_KEY"),
    instructions="""You are Owl Internet's customer service assistant.
Keep responses clear and concise.""",
    tools=TOOLS,
    tool_executors={"look_up_outage": look_up_outage},
)


# ---------------------------------------------------------------------------
# Connector + Server
# ---------------------------------------------------------------------------

connector = VoiceLiveConnector(
    tac=tac,
    config=config,
)

server = TACFastAPIServer(
    tac=tac,
    voice_channel=connector.voice_channel,
)

if __name__ == "__main__":
    server.start()
