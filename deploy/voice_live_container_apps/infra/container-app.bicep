@description('Azure region for all resources.')
param location string = resourceGroup().location

@description('Name prefix for resources.')
param environmentName string

@description('Container image to deploy (e.g. myacr.azurecr.io/tac-voice-live:latest).')
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
          name: 'twilio-tac-auth-token'
          value: twilioTacAuthToken
        }
        {
          name: 'twilio-tac-api-token'
          value: twilioTacApiToken
        }
        {
          name: 'azure-voice-live-api-key'
          value: azureVoiceLiveApiKey
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
            // Voice Live secret
            {
              name: 'AZURE_VOICE_LIVE_API_KEY'
              secretRef: 'azure-voice-live-api-key'
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
      }
    }
  }
}

// ---------------------------------------------------------------------------
// Outputs
// ---------------------------------------------------------------------------

output fqdn string = containerApp.properties.configuration.ingress.fqdn
output name string = containerApp.name
