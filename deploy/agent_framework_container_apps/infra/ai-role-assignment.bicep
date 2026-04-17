@description('Name of the existing Azure AI / Cognitive Services account.')
param accountName string

@description('Principal ID (managed identity) to grant the role to.')
param principalId string

@description('Role definition GUID (not full resource ID).')
param roleDefinitionId string

resource account 'Microsoft.CognitiveServices/accounts@2024-10-01' existing = {
  name: accountName
}

resource roleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: account
  name: guid(account.id, principalId, roleDefinitionId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleDefinitionId)
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}
