// Key Vault for holding the Sentra API key.
// The secret value itself is seeded post-provision by scripts/seed-api-key.sh
// (pulling from AWS Secrets Manager) — Bicep only provisions the empty vault.

@minLength(1)
@maxLength(64)
@description('Name of the azd environment.')
param environmentName string

@description('Region — eastus2 per best-practices.md §11 Azure.')
param location string

@description('Tags applied to every resource.')
param tags object

// Vault names are global, max 24 chars, alphanumeric + hyphens, no consecutive hyphens.
// uniqueString gives 13 chars; "aeg-kv-" prefix + 13 = 20 chars, safe.
var keyVaultName = 'aeg-kv-${uniqueString(resourceGroup().id, environmentName)}'

resource keyVault 'Microsoft.KeyVault/vaults@2024-04-01-preview' = {
  name: keyVaultName
  location: location
  tags: tags
  properties: {
    tenantId: subscription().tenantId
    sku: {
      family: 'A'
      name: 'standard'
    }
    enableRbacAuthorization: true  // RBAC-based, not access policies — modern best practice
    enableSoftDelete: true
    softDeleteRetentionInDays: 7  // demo-and-tear-down friendly, NOT for production
    publicNetworkAccess: 'Enabled'  // Function MI reaches it over Azure backbone; OK for demo
    networkAcls: {
      defaultAction: 'Allow'
      bypass: 'AzureServices'
    }
  }
}

output keyVaultName string = keyVault.name
output keyVaultUri string = keyVault.properties.vaultUri
output keyVaultId string = keyVault.id
