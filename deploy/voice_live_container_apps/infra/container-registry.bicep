@description('Azure region for the Container Registry.')
param location string = resourceGroup().location

@description('Name prefix for the Container Registry (must be globally unique, 5-50 alphanumeric chars).')
param name string

@description('Tags applied to the registry.')
param tags object = {}

// ---------------------------------------------------------------------------
// Azure Container Registry
// ---------------------------------------------------------------------------

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: name
  location: location
  tags: tags
  sku: {
    name: 'Basic'
  }
  properties: {}
}

// ---------------------------------------------------------------------------
// Outputs
// ---------------------------------------------------------------------------

output loginServer string = acr.properties.loginServer
output name string = acr.name
output id string = acr.id
