// Top-level deployment for the AegionAI Azure half of the cross-cloud demo.
// Subscription-scoped so we own resource group creation per azd convention.
//
// Module composition (filled in across Tasks 3.1b and 3.1c of Workstream 15 M3):
//   - function_app.bicep   (3.1b) — Function App + plan + storage + system MI
//   - key_vault.bicep      (3.1b) — Key Vault + Sentra API key secret + Function MI access
//   - ai_foundry.bicep     (3.1c) — Azure AI Foundry project + connection
//
// Note: the azure-verification-agent itself is defined as JSON, not Bicep, at
// infrastructure/azure/agent-spec/azure_verification_agent.json — the AI Foundry
// Agent Service API is still evolving and the spec-as-JSON is more portable
// across SDK churn. AzureConnector loads it at init (WS15 M3 Task 3.4).
//
// Region pairing: centralus ↔ AWS us-east-1 (best-practices.md §11 Azure
// region history). Was eastus2 until PAYG Y1 quota lag forced the move
// 2026-05-23; centralus stays within the LLD 15 §12 p95 ≤120ms budget.

targetScope = 'subscription'

@minLength(1)
@maxLength(64)
@description('Name of the azd environment — also seeds the resource group name.')
param environmentName string

@minLength(1)
@description('Primary Azure region for all resources. Defaults to centralus per WS15 M3 deploy decision 2026-05-23 — see best-practices.md §11 Azure. (Was eastus2; PAYG Y1 quota propagation lag forced the move; centralus is closer-to-us-east-1 enough to stay within the LLD 15 §12 p95 ≤120ms cross-cloud budget.)')
param location string = 'centralus'

@description('Object ID of the deployer (user or service principal). Pulled from azd: `azd env get-values | grep AZURE_PRINCIPAL_ID`. Granted Secrets Officer on Key Vault so the postProvision hook can seed the Sentra API key.')
param deployerObjectId string

@description('Type of the deployer principal — "User" for local dev (azd up from a laptop), "ServicePrincipal" for CI.')
@allowed([
  'User'
  'ServicePrincipal'
])
param deployerPrincipalType string = 'User'

@description('Tags applied to every resource for cost-tracking and tear-down filtering.')
param tags object = {
  Project: 'AegionAI'
  Workstream: 'WS15-M3'
  Owner: 'shashank31mar@gmail.com'
  azd_environment: environmentName
}

// ============================================================================
// Resource Group
// ============================================================================
resource resourceGroup 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: 'aegionai-${environmentName}-rg'
  location: location
  tags: tags
}

// ============================================================================
// Function App + supporting resources (Task 3.1b)
// ============================================================================
module functionApp 'modules/function_app.bicep' = {
  name: 'function-app-deployment'
  scope: resourceGroup
  params: {
    environmentName: environmentName
    location: location
    tags: tags
    keyVaultName: keyVault.outputs.keyVaultName
  }
}

// ============================================================================
// Key Vault (Task 3.1b)
// ============================================================================
module keyVault 'modules/key_vault.bicep' = {
  name: 'key-vault-deployment'
  scope: resourceGroup
  params: {
    environmentName: environmentName
    location: location
    tags: tags
  }
}

// Grant role assignments on the API key vault:
//   - Function App MI gets Secrets User (read, runtime)
//   - Deployer gets Secrets Officer (write, for postProvision seed hook)
module keyVaultRoleAssignment 'modules/key_vault_role.bicep' = {
  name: 'key-vault-role-assignment'
  scope: resourceGroup
  params: {
    keyVaultName: keyVault.outputs.keyVaultName
    principalId: functionApp.outputs.functionAppPrincipalId
    deployerObjectId: deployerObjectId
    deployerPrincipalType: deployerPrincipalType
  }
}

// ============================================================================
// AI Foundry — Azure OpenAI account + gpt-4o-mini deployment (Task 3.1c)
//
// The agent definition itself is NOT a Bicep resource. It lives at
// infrastructure/azure/agent-spec/azure_verification_agent.json and is loaded
// by the AzureConnector (Task 3.3) at dashboard runtime.
// ============================================================================
module aiFoundry 'modules/ai_foundry.bicep' = {
  name: 'ai-foundry-deployment'
  scope: resourceGroup
  params: {
    environmentName: environmentName
    location: location
    tags: tags
    functionAppPrincipalId: functionApp.outputs.functionAppPrincipalId
    deployerObjectId: deployerObjectId
    deployerPrincipalType: deployerPrincipalType
  }
}

// ============================================================================
// Outputs consumed by azd + post-provision hook
// ============================================================================
output AZURE_LOCATION string = location
output AZURE_RESOURCE_GROUP string = resourceGroup.name
output FUNCTION_APP_NAME string = functionApp.outputs.functionAppName
output FUNCTION_APP_HOSTNAME string = functionApp.outputs.functionAppDefaultHostname
output KEY_VAULT_NAME string = keyVault.outputs.keyVaultName
output KEY_VAULT_URI string = keyVault.outputs.keyVaultUri
output OPENAI_ACCOUNT_NAME string = aiFoundry.outputs.openAiAccountName
output OPENAI_ENDPOINT string = aiFoundry.outputs.openAiEndpoint
output OPENAI_DEPLOYMENT_NAME string = aiFoundry.outputs.gpt4oMiniDeploymentName
