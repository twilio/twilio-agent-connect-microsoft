@description('Azure region for all resources.')
param location string = resourceGroup().location

@description('Name prefix for all resources (lowercase, alphanumeric, 3-20 chars).')
param environmentName string

@description('Container image name (set after first deploy, e.g. myacr.azurecr.io/tac-agent-framework:latest).')
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
// Azure AI config
// ---------------------------------------------------------------------------

@description('Azure OpenAI endpoint URL (e.g. https://<resource>.openai.azure.com/).')
param azureOpenAiEndpoint string

@description('Azure OpenAI deployment name.')
param azureOpenAiDeploymentName string

@description('Name of the existing Azure AI / Cognitive Services account (for RBAC).')
param azureOpenAiAccountName string

@description('Resource group of the existing Azure AI account (defaults to current RG).')
param azureOpenAiAccountResourceGroup string = resourceGroup().name

// ---------------------------------------------------------------------------
// Optional config
// ---------------------------------------------------------------------------

@description('TAC Knowledge Base ID (optional).')
param twilioKnowledgeBaseId string = ''

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
    // Azure AI
    azureOpenAiEndpoint: azureOpenAiEndpoint
    azureOpenAiDeploymentName: azureOpenAiDeploymentName
    // Cosmos
    cosmosEndpoint: cosmos.outputs.endpoint
    // Optional
    twilioKnowledgeBaseId: twilioKnowledgeBaseId
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
// RBAC: Cosmos DB data access for Container App's Managed Identity
// ===========================================================================

// Cosmos DB Built-in Data Contributor role definition ID
var cosmosDataContributorRoleId = '00000000-0000-0000-0000-000000000002'
var cosmosAccountName = '${environmentName}-cosmos'

resource cosmosAccount 'Microsoft.DocumentDB/databaseAccounts@2024-11-15' existing = {
  name: cosmosAccountName
}

resource cosmosRoleAssignment 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-11-15' = {
  parent: cosmosAccount
  name: guid(cosmosAccountName, environmentName, cosmosDataContributorRoleId)
  properties: {
    roleDefinitionId: '${cosmosAccount.id}/sqlRoleDefinitions/${cosmosDataContributorRoleId}'
    principalId: app.outputs.principalId
    scope: cosmosAccount.id
  }
}

// ===========================================================================
// RBAC: Cognitive Services OpenAI User on the Azure AI account
// ===========================================================================

// Built-in role: Cognitive Services OpenAI User
var cognitiveServicesOpenAiUserRoleId = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'

module aiRoleAssignment 'ai-role-assignment.bicep' = {
  name: 'ai-role-assignment'
  scope: resourceGroup(azureOpenAiAccountResourceGroup)
  params: {
    accountName: azureOpenAiAccountName
    principalId: app.outputs.principalId
    roleDefinitionId: cognitiveServicesOpenAiUserRoleId
  }
}

// ===========================================================================
// Outputs
// ===========================================================================

output containerAppFqdn string = app.outputs.fqdn
output acrLoginServer string = registry.outputs.loginServer
output cosmosEndpoint string = cosmos.outputs.endpoint
