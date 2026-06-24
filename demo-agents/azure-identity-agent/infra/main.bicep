// Acme Identity agent — Azure Function tool interceptor (LLD 22 §10.5).
// Adapted from the proven WS-15 pattern (infrastructure/azure). B1 Basic Linux plan (Y1 Consumption
// has quota/scale traps on PAYG — best-practices §11). Storage allowSharedKeyAccess=true and
// AzureWebJobsFeatureFlags=EnableWorkerIndexing are REQUIRED for Python v2 Functions.
//
// This provisions the tool-interceptor Function only. The gpt-4o-mini deployment is referenced by
// the traffic generator via AZURE_OPENAI_* env (reuse the WS-15 OpenAI account or provision separately).

@description('Azure region')
param location string = resourceGroup().location

@description('Resource name prefix')
param prefix string = 'acme-identity'

@description('Sentra API Gateway base URL incl. /prod stage')
param sentraApiBase string

@secure()
@description('Sentra usage-plan x-api-key (injected into the Function env, server-side)')
param sentraApiKey string

// WS-A data-plane identity (LLD-26). When all three are set the agent SIGNS its
// validate calls (ES256) under its tenant; the SDK lazy-loads PyJWT[crypto] only
// then, so an empty (default) trio leaves a non-signing deploy byte-identical.
@description('Tenant id for runtime identity signing (WS-A). Empty = signing off.')
param sentraTenantId string = ''
@description('Credential kid for runtime identity signing (WS-A).')
param sentraAgentKid string = ''
@secure()
@description('Agent ES256 private key (PEM) for runtime identity signing (WS-A).')
param sentraAgentPrivateKey string = ''

var identitySettings = (!empty(sentraTenantId) && !empty(sentraAgentKid) && !empty(sentraAgentPrivateKey)) ? [
  { name: 'SENTRA_TENANT_ID', value: sentraTenantId }
  { name: 'SENTRA_AGENT_KID', value: sentraAgentKid }
  { name: 'SENTRA_AGENT_PRIVATE_KEY', value: sentraAgentPrivateKey }
] : []

var storageName = toLower(replace('${prefix}st${uniqueString(resourceGroup().id)}', '-', ''))

resource storage 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: take(storageName, 24)
  location: location
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: {
    allowSharedKeyAccess: true // Function host uses shared-key auth for AzureWebJobsStorage
    minimumTlsVersion: 'TLS1_2'
  }
}

resource plan 'Microsoft.Web/serverfarms@2023-12-01' = {
  name: '${prefix}-plan'
  location: location
  sku: { name: 'B1', tier: 'Basic' } // always-on, ~$13/mo; Y1 has PAYG quota traps
  kind: 'linux'
  properties: { reserved: true }
}

resource insights 'Microsoft.Insights/components@2020-02-02' = {
  name: '${prefix}-insights'
  location: location
  kind: 'web'
  properties: { Application_Type: 'web' }
}

resource func 'Microsoft.Web/sites@2023-12-01' = {
  name: '${prefix}-func'
  location: location
  kind: 'functionapp,linux'
  tags: { 'azd-service-name': 'identity' } // azd publishes the 'identity' service to this resource
  identity: { type: 'SystemAssigned' }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    siteConfig: {
      linuxFxVersion: 'Python|3.11'
      appSettings: concat([
        { name: 'FUNCTIONS_EXTENSION_VERSION', value: '~4' }
        { name: 'FUNCTIONS_WORKER_RUNTIME', value: 'python' }
        { name: 'AzureWebJobsFeatureFlags', value: 'EnableWorkerIndexing' } // v2 model: index functions
        { name: 'AzureWebJobsStorage', value: 'DefaultEndpointsProtocol=https;AccountName=${storage.name};AccountKey=${storage.listKeys().keys[0].value};EndpointSuffix=${environment().suffixes.storage}' }
        { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: insights.properties.ConnectionString }
        { name: 'SENTRA_API_BASE', value: sentraApiBase }
        { name: 'SENTRA_API_KEY', value: sentraApiKey } // demo: plaintext. Prod: @Microsoft.KeyVault(...) ref (best-practices §11 backlog)
        { name: 'SENTRA_VALIDATE_TIMEOUT_S', value: '30' } // cross-cloud cold path (LLD 23 §7)
      ], identitySettings)
    }
  }
}

output functionUrl string = 'https://${func.properties.defaultHostName}/api/tool/{tool_name}'
output functionName string = func.name
