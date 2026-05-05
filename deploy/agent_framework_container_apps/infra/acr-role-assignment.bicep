@description('Name of the Azure Container Registry.')
param acrName string

@description('Principal ID (managed identity) to grant AcrPull.')
param principalId string

// Built-in role: AcrPull
var acrPullRoleId = '7f951dda-4ed3-11e8-9ed4-0a580a5f4b2b'

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = {
  name: acrName
}

resource roleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: acr
  name: guid(acr.id, principalId, acrPullRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRoleId)
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}
