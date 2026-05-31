// Function App + supporting infra for the WS15 M3 tool_interceptor.
// Mirrors the role of `lambda/bedrock_agent_actions/index.py` on the AWS side.
//
// Components:
//   - Storage account (Function runtime requirement)
//   - App Service Plan (Consumption Y1 for cost — Free Trial friendly)
//   - Application Insights (telemetry)
//   - Function App (Python 3.11, HTTP trigger, system-assigned MI)
//   - App settings include the API Gateway URL fixed by Workstream 16.

@minLength(1)
@maxLength(64)
@description('Name of the azd environment.')
param environmentName string

@description('Region — eastus2 per best-practices.md §11 Azure.')
param location string

@description('Tags applied to every resource.')
param tags object

@description('Key Vault name — secret reference will be wired through app settings.')
param keyVaultName string

@description('AWS API Gateway URL — fixed by Workstream 16. The Function POSTs validation requests here.')
param sentraApiEndpoint string = 'https://iw3limi4k7.execute-api.us-east-1.amazonaws.com/prod/v1/validate'

@description('Name of the secret in Key Vault holding the Sentra API key.')
param sentraApiKeySecretName string = 'sentra-api-key'

// Storage account name has tight rules (3-24 lowercase alphanumeric).
// uniqueString() gives 13 chars; "aeg" prefix + first 13 = 16 chars fits.
var storageAccountName = 'aeg${uniqueString(resourceGroup().id, environmentName)}'
var functionAppName = 'aegionai-${environmentName}-func'
var appServicePlanName = 'aegionai-${environmentName}-plan'
var appInsightsName = 'aegionai-${environmentName}-insights'

// ----------------------------------------------------------------------------
// Storage (Function runtime requirement)
// ----------------------------------------------------------------------------
resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageAccountName
  location: location
  tags: tags
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: {
    allowBlobPublicAccess: false
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    // REQUIRED for AzureWebJobsStorage connection-string-based auth used by
    // Function App Y1 Linux Consumption. Microsoft changed the default to
    // disable shared key access for new storage accounts in late 2024
    // (https://learn.microsoft.com/en-us/azure/storage/common/shared-key-authorization-prevent).
    // Without this, the Function host cannot start and returns 503 with zero
    // App Insights traces. Lesson learned WS15 M3, 2026-05-23.
    allowSharedKeyAccess: true
  }
}

// ----------------------------------------------------------------------------
// Application Insights — cost-capped per WS15 M3 cost-optimization pass.
// First 5 GB/month is free. Even with cap=100 MB/day = 3 GB/month we stay
// under the free tier comfortably while preventing runaway ingestion if a
// Function loops on errors.
// ----------------------------------------------------------------------------
resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: appInsightsName
  location: location
  tags: tags
  kind: 'web'
  properties: {
    Application_Type: 'web'
    publicNetworkAccessForIngestion: 'Enabled'
    publicNetworkAccessForQuery: 'Enabled'
    RetentionInDays: 30                            // default 90; we're demo-and-tear-down
    SamplingPercentage: 100                        // keep all traces — volume is low
    DisableIpMasking: false                        // privacy default
  }
}

// Daily cap on ingestion (separate resource — billing feature, not core).
// 0.1 GB/day = 100 MB/day = ~3 GB/month, well under the 5 GB free tier.
resource appInsightsBilling 'Microsoft.Insights/components/CurrentBillingFeatures@2015-05-01' = {
  parent: appInsights
  name: 'Basic'
  properties: {
    CurrentBillingFeatures: ['Basic']
    DataVolumeCap: {
      Cap: json('0.1')                             // GB per day
      WarningThreshold: 90                         // warn at 90% of cap
      StopSendNotificationWhenHitCap: false
    }
  }
}

// ----------------------------------------------------------------------------
// App Service Plan — B1 Basic Linux
//
// Was originally Y1 (Consumption / serverless) for cost, but Y1 in this
// subscription / region (centralus) had the "stuck at 0 workers" issue:
// Function App reported state=Running but zero workers ever spun up, all
// requests returned 503. Lesson learned WS15 M3, 2026-05-23 — see
// best-practices.md §11 Azure region history.
//
// B1 trades $13/mo flat for guaranteed always-on workers and predictable
// scaling, which fits the demo-and-tear-down strategy (tear down via
// `azd down` between demos to stop the meter).
// ----------------------------------------------------------------------------
resource appServicePlan 'Microsoft.Web/serverfarms@2023-12-01' = {
  name: appServicePlanName
  location: location
  tags: tags
  sku: {
    name: 'B1'
    tier: 'Basic'
  }
  properties: {
    reserved: true  // Linux
  }
}

// ----------------------------------------------------------------------------
// Function App
// ----------------------------------------------------------------------------
resource functionApp 'Microsoft.Web/sites@2023-12-01' = {
  name: functionAppName
  location: location
  tags: union(tags, { 'azd-service-name': 'tool-interceptor' })  // links azd deploy to this resource
  kind: 'functionapp,linux'
  identity: {
    type: 'SystemAssigned'  // MI used to read the API key from Key Vault
  }
  properties: {
    serverFarmId: appServicePlan.id
    httpsOnly: true
    siteConfig: {
      linuxFxVersion: 'Python|3.11'
      ftpsState: 'Disabled'
      minTlsVersion: '1.2'
      alwaysOn: true                   // B1 supports this; Y1 did not. Keeps a worker warm.
      appSettings: [
        // Function runtime essentials
        { name: 'AzureWebJobsStorage', value: 'DefaultEndpointsProtocol=https;AccountName=${storageAccount.name};EndpointSuffix=${environment().suffixes.storage};AccountKey=${storageAccount.listKeys().keys[0].value}' }
        { name: 'FUNCTIONS_EXTENSION_VERSION', value: '~4' }
        { name: 'FUNCTIONS_WORKER_RUNTIME', value: 'python' }
        // Removed WEBSITE_RUN_FROM_PACKAGE=1 — that's a Y1 Consumption pattern.
        // B1 uses standard SCM zipdeploy; azd handles the publish flow without WRFP.
        { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsights.properties.ConnectionString }
        // Sentra-specific
        { name: 'SENTRA_API_ENDPOINT', value: sentraApiEndpoint }
        // Pull the API key from Key Vault on each cold start (cached in-memory per LLD 15 §7.2)
        { name: 'SENTRA_API_KEY', value: '@Microsoft.KeyVault(VaultName=${keyVaultName};SecretName=${sentraApiKeySecretName})' }
        { name: 'SENTRA_PLATFORM', value: 'azure_foundry' }
        { name: 'SENTRA_CLOUD_REGION', value: location }
      ]
    }
  }
}

// ----------------------------------------------------------------------------
// Outputs
// ----------------------------------------------------------------------------
output functionAppName string = functionApp.name
output functionAppDefaultHostname string = functionApp.properties.defaultHostName
output functionAppPrincipalId string = functionApp.identity.principalId
