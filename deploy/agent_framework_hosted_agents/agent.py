"""A starter TAC agent with Agent Framework, running in Foundry Hosted Agents.

Edit the prompt and add tools in ``create_agent``.
"""

import os
from pathlib import Path

from agent_framework import Agent
from agent_framework.openai import OpenAIChatClient

from tac_microsoft import (
    TAC,
    AgentFrameworkConnector,
    ConversationSession,
    FileAgentSessionStore,
    SMSChannelConfig,
    TACConfig,
    TACHostedAgentsApp,
)

# --- Your agent: build it with Agent Framework. Change the model, prompt and tools here.

client = OpenAIChatClient(
    azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
    api_key=os.environ["AZURE_OPENAI_API_KEY"],
    model=os.environ["AZURE_OPENAI_DEPLOYMENT_NAME"],
)

SYSTEM_PROMPT = """You are a helpful Twilio assistant. Keep replies short
(1–2 sentences for voice, <320 chars for SMS), clear, and friendly. Avoid
markdown and emoji. Spell out numbers and acronyms naturally so they read
well via text-to-speech. Reference prior context from the conversation
when appropriate."""


def create_agent(session: ConversationSession) -> Agent:
    return client.as_agent(name="TwilioAgent", instructions=SYSTEM_PROMPT)


# --- TAC: connect your agent to Twilio and run it on Foundry Hosted Agents.

tac = TAC(config=TACConfig.from_env())

connector = AgentFrameworkConnector(
    tac=tac,
    create_agent=create_agent,
    # Hosted Agents keeps $HOME across idle periods, so sessions persist there.
    session_store=FileAgentSessionStore(storage_dir=Path(os.environ["HOME"]) / "tac_sessions"),
    sms_config=SMSChannelConfig(memory_mode="always"),
)

server = TACHostedAgentsApp(
    tac=tac,
    voice_channel=connector.voice_channel,
    messaging_channels=[connector.sms_channel],
)

if __name__ == "__main__":
    server.start()
