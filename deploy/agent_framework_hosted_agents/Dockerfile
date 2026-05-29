# Azure Hosted Agents image for TAC + Agent Framework (SMS + voice).
#
# The `[hosted-agents]` extra pulls azure-ai-agentserver-invocations and
# azure-ai-agentserver-core from PyPI. The local SDK wheel under
# wheels/ is still vendored because TACHostedAgentsApp hasn't shipped
# to PyPI yet (the README's setup step builds it via `uv build`).
FROM python:3.13-slim

WORKDIR /app

# Build context is this directory (the agent_framework_hosted_agents
# project root, per azure.yaml `project: .`). Hosted Agents builds from
# the project dir directly, unlike Container Apps where the context is
# the deploy/ parent.
COPY wheels/ /app/wheels/
COPY requirements.txt /app/requirements.txt

# NOTE: only the [hosted-agents] extra is installed here. The
# [agent-framework] extra would pull the full `agent-framework`
# metapackage, which transitively installs every provider (Anthropic,
# Bedrock, Ollama, etc.) and ~triples the image size. requirements.txt
# already pins `agent-framework-openai` (the only provider this server
# uses) so the [agent-framework] extra is unnecessary here.
RUN pip install --no-cache-dir -r /app/requirements.txt \
 && WHEEL=$(ls /app/wheels/twilio_agent_connect_microsoft-*.whl) \
 && pip install --no-cache-dir "${WHEEL}[hosted-agents]"

COPY agent.py /app/agent.py

# Hosted Agents contract: listen on 0.0.0.0:8088
EXPOSE 8088

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

CMD ["python", "agent.py"]
