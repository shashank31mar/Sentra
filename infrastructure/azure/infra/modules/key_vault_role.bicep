// Two role assignments on the Sentra API key vault:
//   1. Function App MI -> Key Vault Secrets User (READ — required for runtime resolution
//      of @Microsoft.KeyVault(...) in SENTRA_API_KEY app setting).
//   2. Deployer (the human/service principal running `azd up`) -> Key Vault Secrets Officer
//      (WRITE — required by scripts/seed-api-key.sh post-provision hook).
// Without #2 the seed hook fails with ForbiddenByRbac (lesson learned 2026-05-23).

@description('Name of the Key Vault to grant access on.')
param keyVaultName string

@description('Principal ID (object ID) of the Function App MI — gets read-only Secrets User role.')
param principalId string

@description('Object ID of the deployer (user or service principal) running `azd up`. Gets Secrets Officer role so the postProvision hook can write the API key.')
param deployerObjectId string

@description('Principal type for the deployer. "User" if running azd locally; "ServicePrincipal" if running from a CI service principal.')
@allowed([
  'User'
  'ServicePrincipal'
])
param deployerPrincipalType string = 'User'

// Built-in role definition IDs:
// https://learn.microsoft.com/en-us/azure/role-based-access-control/built-in-roles
var keyVaultSecretsUserRoleId    = '4633458b-17de-408a-b874-0445c86b69e6'  // read
var keyVaultSecretsOfficerRoleId = 'b86a8fe4-44ce-4948-aee5-eccb2c155cd7'  // read + write

resource keyVault 'Microsoft.KeyVault/vaults@2024-04-01-preview' existing = {
  name: keyVaultName
}

// 1. Function App MI -> Key Vault Secrets User
resource functionAppMiAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: keyVault
  name: guid(keyVault.id, principalId, keyVaultSecretsUserRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', keyVaultSecretsUserRoleId)
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}

// 2. Deployer -> Key Vault Secrets Officer (so seed-api-key.sh can write)
resource deployerAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: keyVault
  name: guid(keyVault.id, deployerObjectId, keyVaultSecretsOfficerRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', keyVaultSecretsOfficerRoleId)
    principalId: deployerObjectId
    principalType: deployerPrincipalType
  }
}
