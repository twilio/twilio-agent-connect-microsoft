// APIM gateway in front of Azure AI Foundry Hosted Agents.
//
// This template provisions:
//   - APIM service (BasicV2+ — Consumption is excluded because it
//     does NOT support WebSocket APIs, which the voice path requires)
//   - System-assigned managed identity on APIM
//   - (Optional) Key Vault with the Twilio Auth Token secret
//   - APIM MI granted Key Vault Secrets User on the (new or existing) vault
//   - Named value referencing the Twilio Auth Token in Key Vault
//   - Backend pointing at the Foundry Hosted Agents account
//   - Three operations + policies:
//       * POST /twilio/webhook  → /invocations (Conversation Orchestrator SMS)
//       * POST /twilio/twiml    → /invocations (Twilio voice form webhook)
//       * WSS  /twilio/ws       → /invocations_ws (Conversation Relay stream)
//
// Key Vault — two modes:
//   1. Bicep creates one (default): leave `existingKeyVaultName` empty
//      and pass the Twilio auth token via the `twilioAuthToken`
//      @secure() param. Bicep creates the vault, seeds the secret, and
//      grants APIM the Secrets User role.
//   2. BYO: set `existingKeyVaultName` (and optionally
//      `existingKeyVaultResourceGroup` if it lives elsewhere). Bicep
//      will reference the existing vault and grant APIM the role on it,
//      but does NOT create the secret — you must seed `TwilioAuthToken`
//      yourself.
//
// Pre-reqs (NOT created here):
//   - APIM's MI granted `Azure AI User` on the Foundry account
//     (the Foundry account commonly lives in a different subscription
//     or RG, so we don't try to do this in-template)
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

@description('APIM SKU. v2 tiers are recommended (faster provisioning + WSS support).')
@allowed([
  'Developer'
  'BasicV2'
  'StandardV2'
  'PremiumV2'
])
param apimSku string = 'BasicV2'

@description('Hosted Agents Foundry account URL (e.g. https://<account>.services.ai.azure.com).')
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

@description('Enable purge protection on the Key Vault when creating one (Mode A). Required by some tenant policies. Once enabled, this is IRREVERSIBLE — the vault gets the full 90-day soft-delete retention and cannot be purged early.')
param keyVaultPurgeProtection bool = true

// ---- Tags ----------------------------------------------------------------

@description('Tags applied to created resources (tenant policy commonly requires created_by).')
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

// Built-in role definition: Key Vault Secrets User
// (4633458b-17de-408a-b874-0445c86b69e6).
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
    // RBAC mode (not access policies). APIM's MI gets a role assignment below.
    enableRbacAuthorization: true
    enableSoftDelete: true
    // When purge protection is on, soft-delete retention has a 90-day
    // floor enforced by Azure; setting it to 7 below would error.
    softDeleteRetentionInDays: keyVaultPurgeProtection ? 90 : 7
    // ``null`` means "leave at tenant default", which works for tenants
    // that don't enforce purge protection. Some tenants reject
    // explicit ``false``, so we only emit ``true`` or omit.
    enablePurgeProtection: keyVaultPurgeProtection ? true : null
    publicNetworkAccess: 'Enabled'
  }
}

// Seed the Twilio Auth Token secret only when creating the vault.
// Reusing an existing vault → assume the secret is already present.
resource newKeyVaultSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if (createKeyVault) {
  parent: newKeyVault
  name: 'TwilioAuthToken'
  properties: {
    value: twilioAuthToken
  }
}

// Reference whichever vault is in use (new or existing) so APIM's named
// value can resolve via vaultUri, and the role assignment can be scoped
// to the right resource. The `existing` keyword is needed even when
// the vault was just declared above, because Bicep doesn't allow scoping
// a role assignment to a conditional resource expression directly.
resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' existing = if (!createKeyVault) {
  name: effectiveKeyVaultName
  scope: resourceGroup(existingKeyVaultResourceGroup)
}

// Compute the URI for both modes — `newKeyVault.properties.vaultUri`
// for mode A, `keyVault.properties.vaultUri` for mode B.
// The two `?` accessors silence BCP318: only one of the resources is
// declared in any given deployment (the other is `null`), and the
// ternary on `createKeyVault` reliably picks the live one.
var effectiveKeyVaultUri = createKeyVault ? newKeyVault!.properties.vaultUri : keyVault!.properties.vaultUri

// ---------------------------------------------------------------------------
// APIM MI → Key Vault Secrets User
// ---------------------------------------------------------------------------
// When reusing a vault in another RG, the role assignment has to be
// scoped there. Bicep doesn't let us pick the scope dynamically with a
// single resource declaration, so we split into two conditional
// assignments (one for each mode). They never both fire.

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

// For an existing vault, the assignment must be deployed at the vault's
// own resource group (which may differ from this deployment's RG). We
// need a separate module for cross-RG scoping.
module apimKeyVaultRoleAssignmentExisting './kv-role-assignment.bicep' = if (!createKeyVault && !skipKeyVaultRoleAssignment) {
  name: 'apim-kv-role-existing'
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
      // The secret must be named exactly `TwilioAuthToken` in Key Vault.
      secretIdentifier: '${effectiveKeyVaultUri}secrets/TwilioAuthToken'
    }
  }
  dependsOn: [
    // Make sure the role assignment exists before APIM tries to
    // resolve the named value (otherwise the resolution fails with 403
    // and APIM can't fetch the secret).
    apimKeyVaultRoleAssignmentNew
    apimKeyVaultRoleAssignmentExisting
    newKeyVaultSecret
  ]
}

// ---------------------------------------------------------------------------
// Backend — Foundry account root
// ---------------------------------------------------------------------------
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
resource twilioApi 'Microsoft.ApiManagement/service/apis@2023-05-01-preview' = {
  parent: apim
  name: 'twilio-tac'
  properties: {
    displayName: 'Twilio TAC → Hosted Agents (HTTP)'
    path: 'twilio'
    protocols: [ 'https' ]
    // Twilio cannot attach APIM subscription keys.
    subscriptionRequired: false
    serviceUrl: hostedAgentsUrl
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
// Separate API resource because APIM models WebSocket APIs distinctly
// (type: 'websocket'). serviceUrl is just the host (no path) so the
// policy's rewrite-uri can set the full path on the backend.
//
// Path is `/ws` to match TACServerConfig.websocket_path default — the
// server emits `wss://{public_domain}/ws?agent_session_id=...` and
// this API receives those upgrades.
resource voiceWsApi 'Microsoft.ApiManagement/service/apis@2023-05-01-preview' = {
  parent: apim
  name: 'twilio-tac-voice-ws'
  properties: {
    displayName: 'Twilio TAC voice (WebSocket) → Hosted Agents'
    // Public path is /twilio/ws — uniqueness is enforced across all APIs.
    path: 'twilio/ws'
    protocols: [ 'wss' ]
    type: 'websocket'
    subscriptionRequired: false
    serviceUrl: 'wss://${hostedAgentsAccountHost}'
  }
}

// WebSocket APIs disallow API-scope policies — must attach to the
// auto-created, unremovable `onHandshake` operation.
resource voiceWsOnHandshake 'Microsoft.ApiManagement/service/apis/operations@2023-05-01-preview' existing = {
  parent: voiceWsApi
  name: 'onHandshake'
}

resource voiceWsPolicy 'Microsoft.ApiManagement/service/apis/operations/policies@2023-05-01-preview' = {
  parent: voiceWsOnHandshake
  name: 'policy'
  properties: {
    format: 'xml'
    // Inject project_name and agent_name as substitutions because policy
    // XML can't reference Bicep params at runtime.
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
    hostedAgentsBackend
  ]
}

// ---------------------------------------------------------------------------
// Outputs
// ---------------------------------------------------------------------------
output apimGatewayUrl string = apim.properties.gatewayUrl
output apimPrincipalId string = apim.identity.principalId
output keyVaultName string = effectiveKeyVaultName
output keyVaultUri string = effectiveKeyVaultUri
// Configure these in your Twilio console / TAC config:
output twilioSmsWebhookUrl string = '${apim.properties.gatewayUrl}/twilio/webhook'
output twilioVoiceTwimlUrl string = '${apim.properties.gatewayUrl}/twilio/twiml'
output twilioVoiceWssUrl string = 'wss://${apim.name}.azure-api.net/twilio/ws'
// Set this as TWILIO_VOICE_PUBLIC_DOMAIN on the agent (no scheme/slash):
output voicePublicDomain string = '${apim.name}.azure-api.net/twilio'
