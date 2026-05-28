// Cross-RG-capable role assignment on an existing Key Vault.
//
// Used by main.bicep when a pre-existing Key Vault is referenced and
// may live in a different resource group from the APIM deployment.
// Bicep can only target a role assignment to a specific scope, and
// that scope must resolve at compile time — so we put the assignment
// in its own module and let the caller decide the scope.

targetScope = 'resourceGroup'

@description('Name of the existing Key Vault.')
param keyVaultName string

@description('Principal ID receiving the role.')
param principalId string

@description('Built-in role definition GUID (e.g. Key Vault Secrets User = 4633458b-17de-408a-b874-0445c86b69e6).')
param roleDefinitionId string

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: keyVaultName
}

resource roleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVault.id, principalId, roleDefinitionId)
  scope: keyVault
  properties: {
    principalId: principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      roleDefinitionId
    )
  }
}
