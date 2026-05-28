# Azure Hosted Agents image for TAC + Agent Framework (SMS + voice).
#
# wheels/ ships the pre-release azure-ai-agentserver-invocations wheel
# (b4 is the first version that exposes /invocations_ws, required for
# Conversation Relay). It's not on PyPI yet, so we vendor it here.
# Once it's published we can drop the wheel and add the dep to
# requirements.txt.
FROM python:3.13-slim

WORKDIR /app

# Build context is this directory (the agent_framework_hosted_agents
# project root, per azure.yaml `project: .`). Hosted Agents builds from
# the project dir directly, unlike Container Apps where the context is
# the deploy/ parent.
COPY wheels/ /app/wheels/
COPY requirements.txt /app/requirements.txt

# Install order matters:
#   1. Pin azure-ai-agentserver-core to 2.0.0b3 FIRST. The invocations
#      b4 wheel declares core>=2.0.0b3 but its code uses request_span(),
#      which was REMOVED in core 2.0.0b4. Pinning to b3 keeps the API
#      contract intact.
#   2. Install the invocations wheel WITHOUT deps so pip doesn't try to
#      upgrade core back to >=2.0.0b3 (which lands b4 again).
#   3. Install requirements.txt — pulls TAC, the Microsoft connector,
#      and Agent Framework from PyPI.
RUN pip install --no-cache-dir --pre azure-ai-agentserver-core==2.0.0b3 \
 && pip install --no-cache-dir --no-deps /app/wheels/azure_ai_agentserver_invocations-*.whl \
 && pip install --no-cache-dir --pre -r /app/requirements.txt \
 && WHEEL=$(ls /app/wheels/twilio_agent_connect_microsoft-*.whl) \
 && pip install --no-cache-dir "${WHEEL}[hosted-agents,agent-framework]"

COPY server.py /app/server.py

# Hosted Agents contract: listen on 0.0.0.0:8088
EXPOSE 8088

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

CMD ["python", "server.py"]
