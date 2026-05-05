@description('Azure region for all resources.')
param location string = resourceGroup().location

@description('Name prefix for all resources (lowercase, alphanumeric, 3-20 chars).')
param environmentName string

@description('Container image name (set after first deploy, e.g. myacr.azurecr.io/tac-voice-live:latest).')
param containerImageName string = ''

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

@description('Public domain for voice WebSocket — set to the Container App FQDN after first deploy.')
param twilioVoicePublicDomain string = ''

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
    // Twilio
    twilioAccountSid: twilioAccountSid
    twilioAuthToken: twilioAuthToken
    twilioApiKey: twilioApiKey
    twilioApiSecret: twilioApiSecret
    twilioPhoneNumber: twilioPhoneNumber
    twilioConversationConfigurationId: twilioConversationConfigurationId
    twilioVoicePublicDomain: !empty(twilioVoicePublicDomain) ? twilioVoicePublicDomain : 'placeholder.azurecontainerapps.io'
    // Voice Live
    azureVoiceLiveEndpoint: azureVoiceLiveEndpoint
    azureVoiceLiveApiKey: azureVoiceLiveApiKey
    azureVoiceLiveModel: azureVoiceLiveModel
    // Optional
    twilioLogLevel: twilioLogLevel
  }
}

// ===========================================================================
// RBAC: AcrPull for Container App's Managed Identity
// ===========================================================================

module acrRoleAssignment 'acr-role-assignment.bicep' = {
  name: 'acr-role-assignment'
  params: {
    acrName: registry.outputs.name
    principalId: app.outputs.principalId
  }
}

// ===========================================================================
// Outputs
// ===========================================================================

output containerAppFqdn string = app.outputs.fqdn
output acrLoginServer string = registry.outputs.loginServer
