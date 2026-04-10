# TAC Voice Live Server — Azure Container Apps Deployment

Complete guide for deploying Twilio Agent Connect (TAC) with Azure AI Foundry Voice Live on Azure Container Apps.

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Azure Services](#azure-services)
- [Deployment](#deployment)

---

## Overview

This deployment runs a voice-only AI agent using:
- **Twilio** — Voice communication platform (Conversation Relay)
- **Azure AI Foundry Voice Live** — Low-latency LLM inference via WebSocket
- **TAC (Twilio Agent Connect)** — Integration middleware

Voice Live manages conversation state server-side. The TAC server acts as a bridge between Twilio's Conversation Relay and Voice Live's WebSocket API, operating in text-only mode (STT/TTS handled by Conversation Relay).

---

## Architecture

```mermaid
graph TB
    Customer([Customer<br/>Phone Call])

    subgraph Twilio["Twilio Cloud"]
        Phone[Phone Number<br/>+1-XXX-XXX-XXXX]
        CRelay[Conversation Relay<br/>STT / TTS]
        Memory[Memory Service<br/>Profile & Context]
    end

    subgraph Azure["Azure Subscription"]
        CA[Container Apps<br/>TAC Server<br/>0.5 vCPU / 1GB RAM<br/>Port 8000]
        VoiceLive[Azure AI Foundry<br/>Voice Live<br/>WebSocket API]
        ACR[Container Registry<br/>Docker Images]
        Logs[Log Analytics<br/>Application Logs]
    end

    Customer -->|1. Phone Call| Phone
    Phone -->|2. Conversation Relay| CRelay
    CRelay -->|3. WebSocket<br/>Text in/out| CA
    CA -->|4. WebSocket<br/>Voice Live API| VoiceLive
    CA -->|5. Retrieve Profile| Memory
    CA -->|6. Write Logs| Logs
    VoiceLive -->|7. LLM Response| CA
    CA -->|8. Text Response| CRelay
    CRelay -->|9. TTS Audio| Phone
    Phone -->|10. Response| Customer
```

---

## Azure Services

### Core Services

| Service | Purpose |
|---------|---------|
| **Container Apps** | Container runtime with built-in ingress, TLS, and auto-scaling |
| **Azure AI Foundry** | Voice Live — low-latency LLM inference via WebSocket |
| **Container Registry** | Docker image storage (Basic SKU) |
| **Log Analytics** | Application logs (30-day retention) |

---

## Deployment

### Prerequisites

**Required:**
- Azure CLI (`az`) installed and logged in
- Docker installed
- Python 3.10+ with `pip`
- Azure subscription with:
  - Azure AI Foundry resource with Voice Live enabled
  - Permission to create Container Apps and Container Registry
- Twilio account with:
  - Auth Token
  - API Key and Secret
  - Phone number
  - Conversation Configuration ID from Conversation Orchestrator

### Step 0: Build and Push Docker Image

**1. Build wheels:**

```bash
cd deploy/voice_live_container_apps
./build-wheels.sh
```

**2. Build Docker image:**

```bash
# Run from the deploy/ directory (parent of voice_live_container_apps)
cd deploy
docker build -t tac-voice-live:latest -f voice_live_container_apps/Dockerfile .
```

### Step 1: Deploy Azure Infrastructure

**1. Create a resource group:**

```bash
az group create \
  --name tac-voice-live-rg \
  --location eastus2
```

**2. Deploy the Bicep template:**

```bash
cd deploy/voice_live_container_apps

az deployment group create \
  --resource-group tac-voice-live-rg \
  --template-file infra/main.bicep \
  --parameters \
    environmentName=tacvoicelive \
    twilioTacAuthToken=YOUR_AUTH_TOKEN \
    twilioTacApiKey=YOUR_API_KEY \
    twilioTacApiToken=YOUR_API_TOKEN \
    twilioTacPhoneNumber=YOUR_PHONE_NUMBER \
    twilioTacConversationConfigurationId=YOUR_CONFIGURATION_ID \
    azureVoiceLiveEndpoint=YOUR_VOICE_LIVE_ENDPOINT \
    azureVoiceLiveApiKey=YOUR_VOICE_LIVE_API_KEY
```

**3. Get the ACR login server from the output:**

```bash
ACR_LOGIN_SERVER=$(az deployment group show \
  --resource-group tac-voice-live-rg \
  --name main \
  --query 'properties.outputs.acrLoginServer.value' -o tsv)
```

### Step 2: Push Image to ACR

```bash
az acr login --name ${ACR_LOGIN_SERVER%%.*}

docker tag tac-voice-live:latest $ACR_LOGIN_SERVER/tac-voice-live:latest
docker push $ACR_LOGIN_SERVER/tac-voice-live:latest
```

### Step 3: Update Container App with Image

Re-deploy with the actual image name and the Container App FQDN as the voice domain:

```bash
FQDN=$(az deployment group show \
  --resource-group tac-voice-live-rg \
  --name main \
  --query 'properties.outputs.containerAppFqdn.value' -o tsv)

az deployment group create \
  --resource-group tac-voice-live-rg \
  --template-file infra/main.bicep \
  --parameters \
    environmentName=tacvoicelive \
    containerImageName=$ACR_LOGIN_SERVER/tac-voice-live:latest \
    twilioTacVoicePublicDomain=$FQDN \
    twilioTacAuthToken=YOUR_AUTH_TOKEN \
    twilioTacApiKey=YOUR_API_KEY \
    twilioTacApiToken=YOUR_API_TOKEN \
    twilioTacPhoneNumber=YOUR_PHONE_NUMBER \
    twilioTacConversationConfigurationId=YOUR_CONFIGURATION_ID \
    azureVoiceLiveEndpoint=YOUR_VOICE_LIVE_ENDPOINT \
    azureVoiceLiveApiKey=YOUR_VOICE_LIVE_API_KEY
```

### Step 4: Get Container App URL

```bash
echo "https://$FQDN"
```

Container Apps provides built-in HTTPS with a valid TLS certificate — no ngrok or reverse proxy needed.

### Step 5: Configure Twilio Webhooks

**Voice (Phone Numbers):**
1. Go to Twilio Console > Phone Numbers > Active Numbers
2. Select your phone number
3. Set **Voice URL:** `https://<FQDN>/twiml` (POST)

### Step 6: Test Your Deployment

Make a phone call to your Twilio phone number to test the deployment.

**View logs:**

```bash
az containerapp logs show \
  --name tacvoicelive-app \
  --resource-group tac-voice-live-rg \
  --type console \
  --follow
```
