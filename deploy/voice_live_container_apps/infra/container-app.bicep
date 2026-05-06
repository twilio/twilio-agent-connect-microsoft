@description('Azure region for all resources.')
param location string = resourceGroup().location

@description('Name prefix for resources.')
param environmentName string

@description('Container image to deploy (e.g. myacr.azurecr.io/tac-voice-live:latest).')
param containerImageName string

@description('ACR login server (e.g. myacr.azurecr.io).')
param acrLoginServer string

@description('Whether the container image lives in ACR (wires up MI pull). Leave false on the first deploy — the placeholder public image does not need ACR auth, and declaring the registries block before the AcrPull role exists causes the first revision to hang on 401 retries.')
param usePrivateRegistry bool = false

@description('Tags applied to every provisioned resource.')
param tags object = {}

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
// Voice Live config
// ---------------------------------------------------------------------------

@description('Azure Voice Live endpoint (no https:// prefix).')
param azureVoiceLiveEndpoint string

@secure()
@description('Azure Voice Live API key.')
param azureVoiceLiveApiKey string

@description('Azure Voice Live model name.')
param azureVoiceLiveModel string = 'gpt-4o'

// ---------------------------------------------------------------------------
// Optional config
// ---------------------------------------------------------------------------

@description('TAC log level.')
param twilioLogLevel string = 'INFO'

// ---------------------------------------------------------------------------
// Log Analytics Workspace
// ---------------------------------------------------------------------------

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: '${environmentName}-logs'
  location: location
  tags: tags
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
  tags: tags
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
// Container App
// ---------------------------------------------------------------------------

resource containerApp 'Microsoft.App/containerApps@2024-10-02-preview' = {
  name: '${environmentName}-app'
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    managedEnvironmentId: containerAppsEnv.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: 8000
        transport: 'auto'
        stickySessions: {
          affinity: 'sticky'
        }
      }
      registries: usePrivateRegistry ? [
        {
          server: acrLoginServer
          identity: 'system'
        }
      ] : []
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
          name: 'azure-voice-live-api-key'
          value: azureVoiceLiveApiKey
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
            // Voice Live secret
            {
              name: 'AZURE_VOICE_LIVE_API_KEY'
              secretRef: 'azure-voice-live-api-key'
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
            // Voice Live config
            {
              name: 'AZURE_VOICE_LIVE_ENDPOINT'
              value: azureVoiceLiveEndpoint
            }
            {
              name: 'AZURE_VOICE_LIVE_MODEL'
              value: azureVoiceLiveModel
            }
          ]
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 3
        rules: [
          {
            name: 'websocket-concurrency'
            tcp: {
              metadata: {
                concurrentConnections: '50'
              }
            }
          }
        ]
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
