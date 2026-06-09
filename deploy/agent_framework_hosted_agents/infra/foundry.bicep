// Foundry account + project + model deployment + container registry for a
// "fresh" Hosted Agents deployment.
//
// Created here (all tag-stamped so tenant tag-enforcement policies pass — a
// bare Foundry project created via the portal/CLI is Denied by such policies
// because those paths don't tag the project resource itself):
//   - Microsoft.CognitiveServices/accounts (kind AIServices, project mgmt on)
//   - .../projects/<project>
//   - .../deployments/<model>  (the chat model the agent uses)
//   - Microsoft.ContainerRegistry/registries  (Hosted Agents pushes/pulls the
//     agent image here; the Foundry account does NOT provide one)
//   - AcrPull grant to the account MI so the sandbox can pull at runtime
//
// This module is invoked by main.bicep only when `createFoundry` is true.

targetScope = 'resourceGroup'

@description('Foundry (CognitiveServices/AIServices) account name. Must be globally unique; it also becomes the *.services.ai.azure.com subdomain.')
param accountName string

@description('Foundry project name created under the account.')
param projectName string

@description('Location for the Foundry account + project. Hosted Agents is only available in select regions; northcentralus is a known-good default.')
param location string = 'northcentralus'

@description('Chat model deployment name (also the deployment id the agent targets).')
param modelName string = 'gpt-5.4-mini'

@description('Model version.')
param modelVersion string = '2026-03-17'

@description('Model deployment SKU name.')
param modelSkuName string = 'GlobalStandard'

@description('Model deployment capacity (thousands of tokens/min). Kept low by default so a fresh subscription with a low quota does not fail provisioning; raise as quota allows.')
param modelCapacity int = 50

@description('Container registry name (alphanumeric only, 5-50 chars, globally unique).')
param acrName string

@description('Tags applied to every created resource (must satisfy tenant tag-enforcement policy, e.g. created_by).')
param tags object

// Built-in role: AcrPull.
var acrPullRoleId = '7f951dda-4ed3-4680-a7ca-43fe172d538d'

// ---------------------------------------------------------------------------
// Foundry account (AIServices) — project management enabled
// ---------------------------------------------------------------------------
resource account 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: accountName
  location: location
  tags: tags
  kind: 'AIServices'
  sku: {
    name: 'S0'
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    // customSubDomainName is required for the *.services.ai.azure.com
    // endpoint the agent + APIM backend use.
    customSubDomainName: accountName
    // Makes this account able to host Foundry projects.
    allowProjectManagement: true
    publicNetworkAccess: 'Enabled'
  }
}

// ---------------------------------------------------------------------------
// Foundry project — tags on the project resource are the policy fix
// ---------------------------------------------------------------------------
resource project 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' = {
  parent: account
  name: projectName
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    displayName: projectName
    description: 'TAC Hosted Agents project'
  }
}

// ---------------------------------------------------------------------------
// Model deployment (chat model the agent runs against)
// ---------------------------------------------------------------------------
resource modelDeployment 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: account
  name: modelName
  sku: {
    name: modelSkuName
    capacity: modelCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: modelName
      version: modelVersion
    }
  }
}

// ---------------------------------------------------------------------------
// Container registry — Hosted Agents pushes/pulls the agent image here
// ---------------------------------------------------------------------------
resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: acrName
  location: location
  tags: tags
  sku: {
    name: 'Basic'
  }
  properties: {
    adminUserEnabled: false
  }
}

// Grant AcrPull to the PROJECT's managed identity — that is the identity the
// Hosted Agents sandbox pulls the agent image under at runtime (confirmed
// against a working deployment; granting the account MI instead fails with
// [ImageError] Failed to pull container image).
resource acrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acr.id, project.id, acrPullRoleId)
  scope: acr
  properties: {
    principalId: project.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRoleId)
  }
}

// ---------------------------------------------------------------------------
// Outputs (consumed by main.bicep)
// ---------------------------------------------------------------------------
output accountName string = account.name
output projectName string = project.name
output accountResourceId string = account.id
// e.g. https://<account>.services.ai.azure.com/api/projects/<project>
output projectEndpoint string = 'https://${accountName}.services.ai.azure.com/api/projects/${projectName}'
output modelDeploymentName string = modelDeployment.name
output acrLoginServer string = acr.properties.loginServer
// Azure OpenAI-compatible endpoint on the account (the agent's chat client
// uses azure_endpoint + this deployment name). The key is fetched by
// deploy.sh (az cognitiveservices account keys list), not output here.
output openAiEndpoint string = account.properties.endpoint
