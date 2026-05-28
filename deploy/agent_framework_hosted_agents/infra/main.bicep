// APIM gateway in front of Azure AI Foundry Hosted Agents.
//
// Provisions:
//   - APIM service with system-assigned MI
//   - Key Vault holding the Twilio Auth Token (Mode A creates one, Mode
//     B references an existing vault — see param descriptions below)
//   - APIM MI granted Key Vault Secrets User on the chosen vault
//   - Backend pointing at the Foundry Hosted Agents account
//   - Three operations + policies:
//       * POST /twilio/webhook  → /invocations (Conversation Orchestrator SMS)
//       * POST /twilio/twiml    → /invocations (Twilio voice form webhook)
//       * WSS  /twilio/ws       → /invocations_ws (Conversation Relay stream)
//
// Not created here:
//   - APIM's MI granted `Foundry User` on the Foundry account. The
//     account commonly lives outside this RG (and sometimes outside
//     this subscription), so the role assignment is left to the
//     deployer — see README step 3.
//
// Deploy:
//   az deployment group create \
//     --resource-group <rg> \
//     --template-file main.bicep \
//     --parameters @main.parameters.json

targetScope = 'resourceGroup'

@description('APIM service name (must be globally unique).')
param apimName string

@description('Publisher email for APIM.')
param publisherEmail string

@description('Publisher name for APIM.')
param publisherName string = 'Twilio Agent'

@description('APIM SKU. Consumption is excluded — it does not host WebSocket APIs, which the voice path requires.')
@allowed([
  'Developer'
  'BasicV2'
  'StandardV2'
  'PremiumV2'
])
param apimSku string = 'BasicV2'

@description('Hosted Agents Foundry account URL plus the agent path. Format: https://<account>.services.ai.azure.com/api/projects/<project>/agents/<agent>/endpoint/protocols. The SMS/voice-twiml policies append `/invocations`; the WS API serviceUrl uses just the host.')
param hostedAgentsUrl string

@description('Foundry project name (set as ?project_name= on the WSS upgrade).')
param projectName string

@description('Foundry agent name (set as ?agent_name= on the WSS upgrade).')
param agentName string

// ---- Key Vault (mode A — create new) -------------------------------------

@description('Name of the Key Vault to create. Leave empty to auto-generate from apimName. Ignored when existingKeyVaultName is set.')
param keyVaultName string = ''

@secure()
@description('Twilio Auth Token. REQUIRED when creating a new Key Vault; ignored when existingKeyVaultName is set.')
param twilioAuthToken string = ''

// ---- Key Vault (mode B — reuse existing) ---------------------------------

@description('Name of an existing Key Vault to reuse. Leave empty to create a new one. The vault must already contain a secret named `TwilioAuthToken`.')
param existingKeyVaultName string = ''

@description('Resource group of the existing Key Vault. Defaults to this deployment\'s RG.')
param existingKeyVaultResourceGroup string = resourceGroup().name

@description('Skip the APIM-MI Key Vault Secrets User role assignment. Set to true when reusing a vault where the role is already granted (Azure rejects duplicate (principal, role, scope) triples even with different role-assignment GUIDs).')
param skipKeyVaultRoleAssignment bool = false

@description('Enable purge protection on a newly-created Key Vault. Required by some tenant policies. Once enabled, this is IRREVERSIBLE — the vault gets the full 90-day soft-delete retention and cannot be purged early.')
param keyVaultPurgeProtection bool = true

// ---- Tags ----------------------------------------------------------------

@description('Tags applied to created resources. The default includes `created_by` because many tenants enforce it via Azure Policy (an update that strips this tag is rejected with RequestDisallowedByPolicy). Override or extend as your tenant requires.')
param tags object = {
  created_by: publisherEmail
  project: 'tac-hosted-agents'
}

// ---------------------------------------------------------------------------
// Derived values
// ---------------------------------------------------------------------------
var createKeyVault = empty(existingKeyVaultName)
// KV names are globally unique and capped at 24 chars; trim and add a
// short hash so two deployments with the same apimName don't collide.
var defaultKeyVaultName = take('kv-${apimName}-${uniqueString(resourceGroup().id, apimName)}', 24)
var newKeyVaultName = empty(keyVaultName) ? defaultKeyVaultName : keyVaultName
var effectiveKeyVaultName = createKeyVault ? newKeyVaultName : existingKeyVaultName
// Bare host extracted from hostedAgentsUrl for the WSS API serviceUrl.
var hostedAgentsAccountHost = split(hostedAgentsUrl, '/')[2]

// Built-in role: Key Vault Secrets User.
var kvSecretsUserRoleId = '4633458b-17de-408a-b874-0445c86b69e6'

// ---------------------------------------------------------------------------
// APIM service
// ---------------------------------------------------------------------------
resource apim 'Microsoft.ApiManagement/service@2023-05-01-preview' = {
  name: apimName
  location: resourceGroup().location
  tags: tags
  sku: {
    name: apimSku
    capacity: 1
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    publisherEmail: publisherEmail
    publisherName: publisherName
  }
}

// ---------------------------------------------------------------------------
// Key Vault — created here (mode A) or referenced (mode B)
// ---------------------------------------------------------------------------
resource newKeyVault 'Microsoft.KeyVault/vaults@2023-07-01' = if (createKeyVault) {
  name: newKeyVaultName
  location: resourceGroup().location
  tags: tags
  properties: {
    sku: {
      family: 'A'
      name: 'standard'
    }
    tenantId: subscription().tenantId
    enableRbacAuthorization: true
    enableSoftDelete: true
    // Purge protection forces a 90-day soft-delete retention floor;
    // setting retention to 7 below would error.
    softDeleteRetentionInDays: keyVaultPurgeProtection ? 90 : 7
    // ``null`` means "leave at tenant default". Some tenants reject an
    // explicit ``false`` via Azure Policy, so we only emit ``true`` or
    // omit the property.
    enablePurgeProtection: keyVaultPurgeProtection ? true : null
    publicNetworkAccess: 'Enabled'
  }
}

// Seed the Twilio Auth Token only when creating the vault. Reusing an
// existing vault → the secret is assumed to already be there.
resource newKeyVaultSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if (createKeyVault) {
  parent: newKeyVault
  name: 'TwilioAuthToken'
  properties: {
    value: twilioAuthToken
  }
}

// `existing` reference for mode B. Bicep doesn't allow scoping a role
// assignment to a conditional resource, so we reference both the new and
// existing vault paths explicitly and pick at the variable level below.
resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' existing = if (!createKeyVault) {
  name: effectiveKeyVaultName
  scope: resourceGroup(existingKeyVaultResourceGroup)
}

// The `?` accessors silence BCP318: only one of the two resources is
// declared in any given deployment; the ternary picks the live one.
var effectiveKeyVaultUri = createKeyVault ? newKeyVault!.properties.vaultUri : keyVault!.properties.vaultUri

// ---------------------------------------------------------------------------
// APIM MI → Key Vault Secrets User
// ---------------------------------------------------------------------------
// Two conditional declarations because Bicep can't pick a role-assignment
// scope dynamically. Only one fires per deployment.

resource apimKeyVaultRoleAssignmentNew 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (createKeyVault && !skipKeyVaultRoleAssignment) {
  name: guid(newKeyVault.id, apim.id, kvSecretsUserRoleId)
  scope: newKeyVault
  properties: {
    principalId: apim.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      kvSecretsUserRoleId
    )
  }
}

// For an existing vault that may live in another RG, the assignment
// must be scoped to that RG. Module wraps a cross-RG deployment so the
// `scope:` expression is statically resolvable.
module apimKeyVaultRoleAssignmentExisting './kv-role-assignment.bicep' = if (!createKeyVault && !skipKeyVaultRoleAssignment) {
  name: 'apim-kv-role-${uniqueString(apim.id, effectiveKeyVaultName)}'
  scope: resourceGroup(existingKeyVaultResourceGroup)
  params: {
    keyVaultName: effectiveKeyVaultName
    principalId: apim.identity.principalId
    roleDefinitionId: kvSecretsUserRoleId
  }
}

// ---------------------------------------------------------------------------
// Named value — TwilioAuthToken (Key Vault reference)
// ---------------------------------------------------------------------------
resource twilioAuthTokenNamedValue 'Microsoft.ApiManagement/service/namedValues@2023-05-01-preview' = {
  parent: apim
  name: 'TwilioAuthToken'
  properties: {
    displayName: 'TwilioAuthToken'
    secret: true
    keyVault: {
      secretIdentifier: '${effectiveKeyVaultUri}secrets/TwilioAuthToken'
    }
  }
  dependsOn: [
    // Block named-value resolution until the role assignment exists,
    // otherwise APIM tries the secret-fetch before RBAC has propagated
    // and gets a 403.
    apimKeyVaultRoleAssignmentNew
    apimKeyVaultRoleAssignmentExisting
    newKeyVaultSecret
  ]
}

// ---------------------------------------------------------------------------
// Backend — Foundry account
// ---------------------------------------------------------------------------
// Both HTTP policies route to this named backend via
// `<set-backend-service backend-id="hosted-agents-backend" />`. The
// WebSocket API skips this and uses its own `serviceUrl` because APIM
// models WSS APIs differently.
resource hostedAgentsBackend 'Microsoft.ApiManagement/service/backends@2023-05-01-preview' = {
  parent: apim
  name: 'hosted-agents-backend'
  properties: {
    protocol: 'http'
    url: hostedAgentsUrl
  }
}

// ---------------------------------------------------------------------------
// HTTP API — /twilio/webhook (SMS) + /twilio/twiml (voice TwiML)
// ---------------------------------------------------------------------------
// No `serviceUrl` here — the policies pick the backend explicitly via
// `set-backend-service`. Keeping the routing in one place (the policy)
// avoids a dual-source-of-truth bug if the backend URL ever changes.
resource twilioApi 'Microsoft.ApiManagement/service/apis@2023-05-01-preview' = {
  parent: apim
  name: 'twilio-tac'
  properties: {
    displayName: 'Twilio TAC → Hosted Agents (HTTP)'
    path: 'twilio'
    protocols: [ 'https' ]
    // Twilio cannot attach APIM subscription keys.
    subscriptionRequired: false
  }
}

// ---- /webhook (Conversation Orchestrator SMS) -----------------------------
resource webhookOp 'Microsoft.ApiManagement/service/apis/operations@2023-05-01-preview' = {
  parent: twilioApi
  name: 'post-webhook'
  properties: {
    displayName: 'Twilio Conversation Orchestrator webhook (SMS)'
    method: 'POST'
    urlTemplate: '/webhook'
    request: {
      headers: [
        { name: 'X-Twilio-Signature', type: 'string', required: true }
        { name: 'i-twilio-idempotency-token', type: 'string', required: false }
      ]
    }
    responses: [
      { statusCode: 200 }
      { statusCode: 400 }
      { statusCode: 401 }
    ]
  }
}

resource webhookPolicy 'Microsoft.ApiManagement/service/apis/operations/policies@2023-05-01-preview' = {
  parent: webhookOp
  name: 'policy'
  properties: {
    format: 'xml'
    value: loadTextContent('./policies/sms-policy.xml')
  }
  dependsOn: [
    twilioAuthTokenNamedValue
    hostedAgentsBackend
  ]
}

// ---- /twiml (voice form webhook) ------------------------------------------
resource voiceTwimlOp 'Microsoft.ApiManagement/service/apis/operations@2023-05-01-preview' = {
  parent: twilioApi
  name: 'post-twiml'
  properties: {
    displayName: 'Twilio voice TwiML webhook'
    method: 'POST'
    urlTemplate: '/twiml'
    request: {
      headers: [
        { name: 'X-Twilio-Signature', type: 'string', required: true }
      ]
    }
    responses: [
      { statusCode: 200 }
      { statusCode: 400 }
      { statusCode: 401 }
    ]
  }
}

resource voiceTwimlPolicy 'Microsoft.ApiManagement/service/apis/operations/policies@2023-05-01-preview' = {
  parent: voiceTwimlOp
  name: 'policy'
  properties: {
    format: 'xml'
    value: loadTextContent('./policies/voice-twiml-policy.xml')
  }
  dependsOn: [
    twilioAuthTokenNamedValue
    hostedAgentsBackend
  ]
}

// ---------------------------------------------------------------------------
// WebSocket API — /twilio/ws (Conversation Relay)
// ---------------------------------------------------------------------------
// Path is `/ws` to match TACServerConfig.websocket_path default — the
// server emits `wss://{public_domain}/ws?agent_session_id=...` and this
// API receives those upgrades. serviceUrl is just the host so the
// policy's `rewrite-uri` can set the full Foundry path on the upgrade.
resource voiceWsApi 'Microsoft.ApiManagement/service/apis@2023-05-01-preview' = {
  parent: apim
  name: 'twilio-tac-voice-ws'
  properties: {
    displayName: 'Twilio TAC voice (WebSocket) → Hosted Agents'
    path: 'twilio/ws'
    protocols: [ 'wss' ]
    type: 'websocket'
    subscriptionRequired: false
    serviceUrl: 'wss://${hostedAgentsAccountHost}'
  }
}

// WebSocket APIs disallow API-scope policies; policy must attach to the
// auto-created `onHandshake` operation.
resource voiceWsOnHandshake 'Microsoft.ApiManagement/service/apis/operations@2023-05-01-preview' existing = {
  parent: voiceWsApi
  name: 'onHandshake'
}

resource voiceWsPolicy 'Microsoft.ApiManagement/service/apis/operations/policies@2023-05-01-preview' = {
  parent: voiceWsOnHandshake
  name: 'policy'
  properties: {
    format: 'xml'
    // project_name + agent_name get injected at deploy time because
    // policy XML can't reference Bicep params at runtime.
    value: replace(
      replace(
        loadTextContent('./policies/voice-ws-policy.xml'),
        '__PROJECT_NAME__',
        projectName
      ),
      '__AGENT_NAME__',
      agentName
    )
  }
  dependsOn: [
    twilioAuthTokenNamedValue
  ]
}

// ---------------------------------------------------------------------------
// Outputs
// ---------------------------------------------------------------------------
output apimGatewayUrl string = apim.properties.gatewayUrl
output apimPrincipalId string = apim.identity.principalId
output keyVaultName string = effectiveKeyVaultName
output keyVaultUri string = effectiveKeyVaultUri
// Configure these in your Twilio console:
output twilioSmsWebhookUrl string = '${apim.properties.gatewayUrl}/twilio/webhook'
output twilioVoiceTwimlUrl string = '${apim.properties.gatewayUrl}/twilio/twiml'
output twilioVoiceWssUrl string = 'wss://${apim.name}.azure-api.net/twilio/ws'
// Set on the agent as TWILIO_VOICE_PUBLIC_DOMAIN (no scheme/slash):
output voicePublicDomain string = '${apim.name}.azure-api.net/twilio'
