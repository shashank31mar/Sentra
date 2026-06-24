// Acme Telecom agent — Azure Function tool interceptor (LLD 22 §10.5).
// Identical pattern to the identity agent (see azure-identity-agent/infra/main.bicep for notes):
// B1 Basic Linux, storage allowSharedKeyAccess=true, AzureWebJobsFeatureFlags=EnableWorkerIndexing.

@description('Azure region')
param location string = resourceGroup().location

@description('Resource name prefix')
param prefix string = 'acme-telecom'

@description('Sentra API Gateway base URL incl. /prod stage')
param sentraApiBase string

@secure()
@description('Sentra usage-plan x-api-key (injected into the Function env, server-side)')
param sentraApiKey string

// WS-A data-plane identity (LLD-26). When all three are set the agent SIGNS its
// validate calls (ES256) under its tenant; empty (default) → non-signing deploy
// is byte-identical (SDK lazy-loads PyJWT[crypto] only when the trio is present).
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
  properties: { allowSharedKeyAccess: true, minimumTlsVersion: 'TLS1_2' }
}

resource plan 'Microsoft.Web/serverfarms@2023-12-01' = {
  name: '${prefix}-plan'
  location: location
  sku: { name: 'B1', tier: 'Basic' }
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
  tags: { 'azd-service-name': 'telecom' } // azd publishes the 'telecom' service to this resource
  identity: { type: 'SystemAssigned' }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    siteConfig: {
      linuxFxVersion: 'Python|3.11'
      appSettings: concat([
        { name: 'FUNCTIONS_EXTENSION_VERSION', value: '~4' }
        { name: 'FUNCTIONS_WORKER_RUNTIME', value: 'python' }
        { name: 'AzureWebJobsFeatureFlags', value: 'EnableWorkerIndexing' }
        { name: 'AzureWebJobsStorage', value: 'DefaultEndpointsProtocol=https;AccountName=${storage.name};AccountKey=${storage.listKeys().keys[0].value};EndpointSuffix=${environment().suffixes.storage}' }
        { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: insights.properties.ConnectionString }
        { name: 'SENTRA_API_BASE', value: sentraApiBase }
        { name: 'SENTRA_API_KEY', value: sentraApiKey }
        { name: 'SENTRA_VALIDATE_TIMEOUT_S', value: '30' }
      ], identitySettings)
    }
  }
}

output functionUrl string = 'https://${func.properties.defaultHostName}/api/tool/{tool_name}'
output functionName string = func.name
