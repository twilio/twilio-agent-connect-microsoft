@description('Azure region for all resources.')
param location string = resourceGroup().location

@description('Name prefix for all resources (lowercase, alphanumeric, 3-20 chars).')
param environmentName string

@description('Container image name (set after first deploy, e.g. myacr.azurecr.io/tac-voice-live:latest).')
param containerImageName string = ''

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

@description('Public domain for voice WebSocket — set to the Container App FQDN after first deploy.')
param twilioTacVoicePublicDomain string = ''

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

// ===========================================================================
// Module: Container Registry
// ===========================================================================

module registry 'container-registry.bicep' = {
  name: 'registry'
  params: {
    location: location
    name: '${replace(environmentName, '-', '')}acr'
  }
}

// ===========================================================================
// Module: Container App
// ===========================================================================

// Use a placeholder image for the first deploy (before pushing to ACR)
var imageName = !empty(containerImageName) ? containerImageName : 'mcr.microsoft.com/k8se/quickstart:latest'

module app 'container-app.bicep' = {
  name: 'container-app'
  params: {
    location: location
    environmentName: environmentName
    containerImageName: imageName
    acrLoginServer: registry.outputs.loginServer
    acrName: registry.outputs.name
    // Twilio
    twilioTacAuthToken: twilioTacAuthToken
    twilioTacApiKey: twilioTacApiKey
    twilioTacApiToken: twilioTacApiToken
    twilioTacPhoneNumber: twilioTacPhoneNumber
    twilioTacConversationConfigurationId: twilioTacConversationConfigurationId
    twilioTacVoicePublicDomain: !empty(twilioTacVoicePublicDomain) ? twilioTacVoicePublicDomain : 'placeholder.azurecontainerapps.io'
    // Voice Live
    azureVoiceLiveEndpoint: azureVoiceLiveEndpoint
    azureVoiceLiveApiKey: azureVoiceLiveApiKey
    azureVoiceLiveModel: azureVoiceLiveModel
    // Optional
    twilioTacLogLevel: twilioTacLogLevel
  }
}

// ===========================================================================
// Outputs
// ===========================================================================

output containerAppFqdn string = app.outputs.fqdn
output acrLoginServer string = registry.outputs.loginServer
