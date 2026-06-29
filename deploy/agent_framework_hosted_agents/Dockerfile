# Azure Hosted Agents image for TAC + Agent Framework (SMS + voice).
#
# twilio-agent-connect-microsoft[hosted-agents] (and its azure-ai-agentserver-*
# runtime deps) install from PyPI via requirements.txt — see that file for the
# pin and rationale.
FROM python:3.13-slim

WORKDIR /app

# Build context is this directory (the agent_framework_hosted_agents
# project root, per azure.yaml `project: .`). Hosted Agents builds from
# the project dir directly, unlike Container Apps where the context is
# the deploy/ parent.
COPY requirements.txt /app/requirements.txt

# NOTE: only the [hosted-agents] extra is installed here (via
# requirements.txt). The [agent-framework] extra would pull the full
# `agent-framework` metapackage, which transitively installs every provider
# (Anthropic, Bedrock, Ollama, etc.) and ~triples the image size.
# requirements.txt already pins `agent-framework-openai` (the only provider
# this server uses) so the [agent-framework] extra is unnecessary here.
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY agent.py /app/agent.py

# Hosted Agents contract: listen on 0.0.0.0:8088
EXPOSE 8088

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# This container intentionally runs as root — see the nosemgrep below.
#
# Unlike the Container Apps images (which run as a non-root `appuser`),
# the Hosted Agents runtime mounts the per-session persisted filesystem
# at $HOME=/home/session owned by root:root mode 0755. That mount is the
# ONLY path the platform preserves across the 15-minute idle eviction
# (Foundry docs: "$HOME and /files content are persisted across turns and
# across idle periods"), and it's what FileAgentSessionStore writes to
# (see agent.py: $HOME/tac_sessions). A non-root user cannot write or
# mkdir under that mount, and the mount shadows any build-time chown — so
# a non-root container cannot persist session state at all. Running as
# root is required to use the platform's persisted store without an
# external store (Cosmos, etc.). The sandbox is per-session VM-isolated by
# the platform, so the in-container privilege surface is already bounded.
#
# nosemgrep: dockerfile.security.missing-user.missing-user
CMD ["python", "agent.py"]
