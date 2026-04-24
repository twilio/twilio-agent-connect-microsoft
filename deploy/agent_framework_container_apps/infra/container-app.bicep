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

@description('Twilio Account SID.')
param twilioAccountSid string

@secure()
@description('Twilio Auth Token.')
param twilioAuthToken string

@description('Twilio API Key SID.')
param twilioApiKey string

@secure()
@description('Twilio API Key Secret.')
param twilioApiSecret string

// ---------------------------------------------------------------------------
// Twilio config
// ---------------------------------------------------------------------------

@description('Twilio phone number (E.164 format).')
param twilioPhoneNumber string

@description('Twilio Conversation Configuration ID.')
param twilioConversationConfigurationId string

@description('Public domain for voice WebSocket (e.g. your-app.azurecontainerapps.io).')
param twilioVoicePublicDomain string

// ---------------------------------------------------------------------------
// Azure AI config
// ---------------------------------------------------------------------------

@description('Azure OpenAI endpoint URL (e.g. https://<resource>.openai.azure.com/).')
param azureOpenAiEndpoint string

@description('Azure OpenAI deployment name.')
param azureOpenAiDeploymentName string

// ---------------------------------------------------------------------------
// Cosmos DB config
// ---------------------------------------------------------------------------

@description('Cosmos DB endpoint URL.')
param cosmosEndpoint string

// ---------------------------------------------------------------------------
// Optional config
// ---------------------------------------------------------------------------

@description('TAC Knowledge Base ID (optional).')
param twilioKnowledgeBaseId string = ''

@description('TAC log level.')
param twilioLogLevel string = 'INFO'

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

resource containerAppsEnv 'Microsoft.App/managedEnvironments@2024-10-02-preview' = {
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

resource containerApp 'Microsoft.App/containerApps@2024-10-02-preview' = {
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
        // Note: stickySessions must be enabled post-deploy via Azure Portal or CLI:
        //   az containerapp ingress sticky-sessions set -n <app> -g <rg> --affinity sticky
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
          name: 'twilio-auth-token'
          value: twilioAuthToken
        }
        {
          name: 'twilio-api-secret'
          value: twilioApiSecret
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
              name: 'TWILIO_AUTH_TOKEN'
              secretRef: 'twilio-auth-token'
            }
            {
              name: 'TWILIO_API_SECRET'
              secretRef: 'twilio-api-secret'
            }
            // Twilio config
            {
              name: 'TWILIO_ACCOUNT_SID'
              value: twilioAccountSid
            }
            {
              name: 'TWILIO_API_KEY'
              value: twilioApiKey
            }
            {
              name: 'TWILIO_PHONE_NUMBER'
              value: twilioPhoneNumber
            }
            {
              name: 'TWILIO_CONVERSATION_CONFIGURATION_ID'
              value: twilioConversationConfigurationId
            }
            {
              name: 'TWILIO_VOICE_PUBLIC_DOMAIN'
              value: twilioVoicePublicDomain
            }
            {
              name: 'TWILIO_LOG_LEVEL'
              value: twilioLogLevel
            }
            // Azure OpenAI
            {
              name: 'AZURE_OPENAI_ENDPOINT'
              value: azureOpenAiEndpoint
            }
            {
              name: 'AZURE_OPENAI_DEPLOYMENT_NAME'
              value: azureOpenAiDeploymentName
            }
            // Cosmos DB (auth via Managed Identity)
            {
              name: 'AZURE_COSMOS_ENDPOINT'
              value: cosmosEndpoint
            }
            // Optional
            {
              name: 'TWILIO_KNOWLEDGE_BASE_ID'
              value: twilioKnowledgeBaseId
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
