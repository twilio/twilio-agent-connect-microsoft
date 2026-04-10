@description('Azure region for the Container Registry.')
param location string = resourceGroup().location

@description('Name prefix for the Container Registry (must be globally unique, 5-50 alphanumeric chars).')
param name string

// ---------------------------------------------------------------------------
// Azure Container Registry
// ---------------------------------------------------------------------------

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: name
  location: location
  sku: {
    name: 'Basic'
  }
  properties: {
    adminUserEnabled: true
  }
}

// ---------------------------------------------------------------------------
// Outputs
// ---------------------------------------------------------------------------

output loginServer string = acr.properties.loginServer
output name string = acr.name
output id string = acr.id
