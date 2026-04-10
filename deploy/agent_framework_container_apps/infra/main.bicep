@description('Azure region for all resources.')
param location string = resourceGroup().location

@description('Name prefix for all resources (lowercase, alphanumeric, 3-20 chars).')
param environmentName string

@description('Container image name (set after first deploy, e.g. myacr.azurecr.io/tac-agent-framework:latest).')
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
// Azure AI config
// ---------------------------------------------------------------------------

@description('Azure AI project endpoint URL.')
param azureAiProjectEndpoint string

@description('Azure OpenAI deployment name.')
param azureAiDeploymentName string = 'gpt-4o'

// ---------------------------------------------------------------------------
// Optional config
// ---------------------------------------------------------------------------

@description('TAC Knowledge Base ID (optional).')
param twilioTacKnowledgeBaseId string = ''

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
// Module: Cosmos DB (deployed first — no dependency on Container App)
// ===========================================================================

module cosmos 'cosmos-db.bicep' = {
  name: 'cosmos-db'
  params: {
    location: location
    accountName: '${environmentName}-cosmos'
  }
}

// ===========================================================================
// Module: Container App (depends on Cosmos endpoint + ACR)
// ===========================================================================

// Use a placeholder image for the first deploy (before pushing to ACR)
var imageName = !empty(containerImageName) ? containerImageName : '${registry.outputs.loginServer}/tac-agent-framework:latest'

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
    // Azure AI
    azureAiProjectEndpoint: azureAiProjectEndpoint
    azureAiDeploymentName: azureAiDeploymentName
    // Cosmos
    cosmosEndpoint: cosmos.outputs.endpoint
    // Optional
    twilioTacKnowledgeBaseId: twilioTacKnowledgeBaseId
    twilioTacLogLevel: twilioTacLogLevel
  }
}

// ===========================================================================
// RBAC: Cosmos DB data access for Container App's Managed Identity
// ===========================================================================

// Cosmos DB Built-in Data Contributor role definition ID
var cosmosDataContributorRoleId = '00000000-0000-0000-0000-000000000002'

resource cosmosAccount 'Microsoft.DocumentDB/databaseAccounts@2024-05-15' existing = {
  name: cosmos.outputs.accountName
}

resource cosmosRoleAssignment 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-05-15' = {
  parent: cosmosAccount
  name: guid(cosmosAccount.id, app.outputs.principalId, cosmosDataContributorRoleId)
  properties: {
    roleDefinitionId: '${cosmosAccount.id}/sqlRoleDefinitions/${cosmosDataContributorRoleId}'
    principalId: app.outputs.principalId
    scope: cosmosAccount.id
  }
}

// ===========================================================================
// Outputs
// ===========================================================================

output containerAppFqdn string = app.outputs.fqdn
output acrLoginServer string = registry.outputs.loginServer
output cosmosEndpoint string = cosmos.outputs.endpoint
