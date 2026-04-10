@description('Azure region for all resources.')
param location string = resourceGroup().location

@description('Name prefix for resources.')
param environmentName string

@description('Container image to deploy (e.g. myacr.azurecr.io/tac-agent-framework:latest).')
param containerImageName string

@description('ACR login server (e.g. myacr.azurecr.io).')
param acrLoginServer string

@description('ACR resource name for credential pull.')
param acrName string

// ---------------------------------------------------------------------------
// Twilio secrets
// ---------------------------------------------------------------------------

@secure()
@description('Twilio Auth Token.')
param twilioTacAuthToken string

@description('Twilio API Key.')
param twilioTacApiKey string

@secure()
@description('Twilio API Token (secret).')
param twilioTacApiToken string

// ---------------------------------------------------------------------------
// Twilio config
// ---------------------------------------------------------------------------

@description('Twilio phone number (E.164 format).')
param twilioTacPhoneNumber string

@description('Twilio Conversation Configuration ID.')
param twilioTacConversationConfigurationId string

@description('Public domain for voice WebSocket (e.g. your-app.azurecontainerapps.io).')
param twilioTacVoicePublicDomain string

// ---------------------------------------------------------------------------
// Azure AI config
// ---------------------------------------------------------------------------

@description('Azure AI project endpoint URL.')
param azureAiProjectEndpoint string

@description('Azure OpenAI deployment name.')
param azureAiDeploymentName string = 'gpt-4o'

// ---------------------------------------------------------------------------
// Cosmos DB config
// ---------------------------------------------------------------------------

@description('Cosmos DB endpoint URL.')
param cosmosEndpoint string

// ---------------------------------------------------------------------------
// Optional config
// ---------------------------------------------------------------------------

@description('TAC Knowledge Base ID (optional).')
param twilioTacKnowledgeBaseId string = ''

@description('TAC log level.')
param twilioTacLogLevel string = 'INFO'

// ---------------------------------------------------------------------------
// Log Analytics Workspace
// ---------------------------------------------------------------------------

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: '${environmentName}-logs'
  location: location
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
  }
}

// ---------------------------------------------------------------------------
// Container Apps Environment
// ---------------------------------------------------------------------------

resource containerAppsEnv 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: '${environmentName}-env'
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalytics.properties.customerId
        sharedKey: logAnalytics.listKeys().primarySharedKey
      }
    }
  }
}

// ---------------------------------------------------------------------------
// ACR credentials
// ---------------------------------------------------------------------------

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = {
  name: acrName
}

// ---------------------------------------------------------------------------
// Container App
// ---------------------------------------------------------------------------

resource containerApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: '${environmentName}-app'
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    managedEnvironmentId: containerAppsEnv.id
    configuration: {
      ingress: {
        external: true
        targetPort: 8000
        transport: 'auto'
        stickySessions: {
          affinity: 'sticky'
        }
      }
      registries: [
        {
          server: acrLoginServer
          username: acr.listCredentials().username
          passwordSecretRef: 'acr-password'
        }
      ]
      secrets: [
        {
          name: 'twilio-tac-auth-token'
          value: twilioTacAuthToken
        }
        {
          name: 'twilio-tac-api-token'
          value: twilioTacApiToken
        }
        {
          name: 'acr-password'
          value: acr.listCredentials().passwords[0].value
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'tac-server'
          image: containerImageName
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: [
            // Twilio secrets
            {
              name: 'TWILIO_TAC_AUTH_TOKEN'
              secretRef: 'twilio-tac-auth-token'
            }
            {
              name: 'TWILIO_TAC_API_TOKEN'
              secretRef: 'twilio-tac-api-token'
            }
            // Twilio config
            {
              name: 'TWILIO_TAC_API_KEY'
              value: twilioTacApiKey
            }
            {
              name: 'TWILIO_TAC_PHONE_NUMBER'
              value: twilioTacPhoneNumber
            }
            {
              name: 'TWILIO_TAC_CONVERSATION_CONFIGURATION_ID'
              value: twilioTacConversationConfigurationId
            }
            {
              name: 'TWILIO_TAC_VOICE_PUBLIC_DOMAIN'
              value: twilioTacVoicePublicDomain
            }
            {
              name: 'TWILIO_TAC_ENVIRONMENT'
              value: 'prod'
            }
            {
              name: 'TWILIO_TAC_LOG_LEVEL'
              value: twilioTacLogLevel
            }
            // Azure AI
            {
              name: 'AZURE_AI_PROJECT_ENDPOINT'
              value: azureAiProjectEndpoint
            }
            {
              name: 'AZURE_AI_DEPLOYMENT_NAME'
              value: azureAiDeploymentName
            }
            // Cosmos DB (auth via Managed Identity)
            {
              name: 'AZURE_COSMOS_ENDPOINT'
              value: cosmosEndpoint
            }
            // Optional
            {
              name: 'TWILIO_TAC_KNOWLEDGE_BASE_ID'
              value: twilioTacKnowledgeBaseId
            }
          ]
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 3
      }
    }
  }
}

// ---------------------------------------------------------------------------
// Outputs
// ---------------------------------------------------------------------------

output fqdn string = containerApp.properties.configuration.ingress.fqdn
output principalId string = containerApp.identity.principalId
output name string = containerApp.name
