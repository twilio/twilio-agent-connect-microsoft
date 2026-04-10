@description('Azure region for Cosmos DB.')
param location string = resourceGroup().location

@description('Cosmos DB account name (must be globally unique).')
param accountName string

@description('Database name.')
param databaseName string = 'tac'

@description('Container name.')
param containerName string = 'sessions'

// ---------------------------------------------------------------------------
// Cosmos DB Account — NoSQL API, Serverless
// ---------------------------------------------------------------------------

resource cosmosAccount 'Microsoft.DocumentDB/databaseAccounts@2024-05-15' = {
  name: accountName
  location: location
  kind: 'GlobalDocumentDB'
  properties: {
    databaseAccountOfferType: 'Standard'
    locations: [
      {
        locationName: location
        failoverPriority: 0
      }
    ]
    capabilities: [
      {
        name: 'EnableServerless'
      }
    ]
    consistencyPolicy: {
      defaultConsistencyLevel: 'Session'
    }
  }
}

// ---------------------------------------------------------------------------
// Database + Container
// ---------------------------------------------------------------------------

resource database 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2024-05-15' = {
  parent: cosmosAccount
  name: databaseName
  properties: {
    resource: {
      id: databaseName
    }
  }
}

resource sqlContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/sqlContainers@2024-05-15' = {
  parent: database
  name: containerName
  properties: {
    resource: {
      id: containerName
      partitionKey: {
        paths: ['/id']
        kind: 'Hash'
      }
      defaultTtl: -1  // TTL enabled but no default expiry (set per-document)
    }
  }
}

// ---------------------------------------------------------------------------
// Outputs
// ---------------------------------------------------------------------------

output endpoint string = cosmosAccount.properties.documentEndpoint
output accountName string = cosmosAccount.name
output accountId string = cosmosAccount.id
