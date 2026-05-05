"""TAC Server with Voice Live — Container Apps deployment.

This is a starting point. Edit the system prompt, tools, and Voice Live
configuration below to match your use case.

For more details on Voice Live configuration, see:
    getting_started/examples/voice_live/basic.py
"""

from __future__ import annotations

import os

from tac_microsoft import (
    TAC,
    TACConfig,
    TACFastAPIServer,
    VoiceLiveConnector,
    VoiceLiveConfig,
)

# ---------------------------------------------------------------------------
# TAC + Voice Live setup
# ---------------------------------------------------------------------------

tac = TAC(config=TACConfig.from_env())

config = VoiceLiveConfig(
    endpoint=os.environ["AZURE_VOICE_LIVE_ENDPOINT"],
    model=os.environ.get("AZURE_VOICE_LIVE_MODEL", "gpt-4o"),
    api_key=os.environ.get("AZURE_VOICE_LIVE_API_KEY"),
    # Edit the system prompt below
    instructions="""You are a helpful customer service assistant.
Keep responses clear and concise.""",
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
