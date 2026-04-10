# TAC Azure Deployment Guide

Production deployment options for TAC Azure connectors.

## Available Deployments

### Azure Container Apps with Agent Framework

Deploy Microsoft Agent Framework agents to Azure Container Apps with Cosmos DB session persistence.

**Guide:** [`agent_framework_container_apps/README.md`](agent_framework_container_apps/README.md)

**Includes:**
- Container Apps + Cosmos DB infrastructure (Bicep)
- Docker multi-stage build
- Managed Identity for Cosmos DB access
- Architecture diagrams

**Best for:**
- Production voice + SMS agents using Azure OpenAI or Azure AI Foundry
- Horizontally scalable deployments with session persistence
- Full-featured agents with memory, knowledge, and custom tools

### Azure Container Apps with Voice Live

Deploy Azure AI Foundry Voice Live agents to Azure Container Apps.

**Guide:** [`voice_live_container_apps/README.md`](voice_live_container_apps/README.md)

**Includes:**
- Container Apps infrastructure (Bicep)
- Docker multi-stage build
- Voice Live WebSocket integration

**Best for:**
- Voice-only agents using Azure AI Foundry Voice Live
- Low-latency voice with server-managed conversation state
- Simpler deployments without session persistence requirements

## Deployment Architecture

### Agent Framework Connector
TAC Server runs on Container Apps and creates per-conversation Agent Framework agents. Sessions are persisted in Cosmos DB for horizontal scaling. Supports both voice (WebSocket) and SMS (HTTP) channels.

### Voice Live Connector
TAC Server runs on Container Apps and streams text to Azure AI Foundry Voice Live over WebSocket. Voice Live manages conversation state server-side. Voice-only — no SMS support.

## Getting Started

1. Choose your connector type
2. Follow the appropriate deployment guide
3. Configure environment variables
4. Deploy infrastructure

For local development and testing, see [`../getting_started/README.md`](../getting_started/README.md)
