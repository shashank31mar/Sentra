// Azure AI Foundry — Workstream 15 M3 Task 3.1c.
//
// Provisions:
//   1. Azure OpenAI account (the Foundry-managed model service)
//   2. gpt-4o-mini Standard deployment on that account
//   3. Role assignment granting the Function App MI permission to invoke the
//      OpenAI endpoint (Cognitive Services User role)
//
// The "azure-verification-agent" itself is NOT a Bicep resource — it's a
// system prompt + tool definitions stored at
// infrastructure/azure/agent-spec/azure_verification_agent.json. The
// AzureConnector (Task 3.3) loads this spec and invokes gpt-4o-mini with
// function-calling, where the tools point at the Function App URL.
//
// Cost: gpt-4o-mini Standard is pay-per-token only ($0.15/1M input, $0.60/1M
// output) — no fixed deployment cost. Demo-and-tear-down friendly.

@minLength(1)
@maxLength(64)
@description('Name of the azd environment.')
param environmentName string

@description('Region for the OpenAI account. centralus has gpt-4o-mini availability per `az cognitiveservices model list -l centralus`.')
param location string

@description('Tags applied to every resource.')
param tags object

@description('Function App MI principal ID — gets Cognitive Services User role on the OpenAI account so the Function (and AzureConnector via Function) can invoke gpt-4o-mini.')
param functionAppPrincipalId string

@description('Deployer object ID — gets Cognitive Services OpenAI User role so the local dashboard / dev can also invoke during demo.')
param deployerObjectId string

@description('Type of the deployer principal — "User" for local dev, "ServicePrincipal" for CI.')
@allowed([ 'User', 'ServicePrincipal' ])
param deployerPrincipalType string = 'User'

// OpenAI account name: 2-64 chars, lowercase alphanumeric + hyphens.
// Predictable name keeps the endpoint URL stable across re-provisions.
var openAiAccountName = 'aegionai-${environmentName}-openai'
var modelDeploymentName = 'gpt-4o-mini'

// ----------------------------------------------------------------------------
// Azure OpenAI account (S0 = Standard tier; no fixed cost)
// ----------------------------------------------------------------------------
resource openAiAccount 'Microsoft.CognitiveServices/accounts@2024-10-01' = {
  name: openAiAccountName
  location: location
  tags: tags
  kind: 'OpenAI'
  sku: { name: 'S0' }
  identity: { type: 'SystemAssigned' }
  properties: {
    customSubDomainName: openAiAccountName  // required for keyless (MI) auth
    publicNetworkAccess: 'Enabled'
    networkAcls: {
      defaultAction: 'Allow'
      bypass: 'AzureServices'
    }
    disableLocalAuth: false  // keep API-key path open for local dev; MI is preferred for prod
  }
}

// ----------------------------------------------------------------------------
// gpt-4o-mini Standard deployment
//
// Capacity is in 1000 TPM units. 100 = 100k TPM, plenty for demo iteration.
// PAYG default quota for gpt-4o-mini in centralus is typically 250K TPM
// (verify with `az cognitiveservices usage list -l centralus`); 100K stays
// comfortably under that.
// ----------------------------------------------------------------------------
resource gpt4oMiniDeployment 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = {
  parent: openAiAccount
  name: modelDeploymentName
  sku: {
    // GlobalStandard not Standard — regional Standard is unavailable in
    // centralus for gpt-4o-mini 2024-07-18 (lesson learned WS15 M3, 2026-05-23,
    // see `az cognitiveservices model list -l centralus`). GlobalStandard uses
    // a cross-region capacity pool; pricing identical to Standard pay-per-token.
    name: 'GlobalStandard'
    capacity: 100  // 100k TPM
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: 'gpt-4o-mini'
      version: '2024-07-18'
    }
    versionUpgradeOption: 'OnceCurrentVersionExpired'
    raiPolicyName: 'Microsoft.DefaultV2'
  }
}

// ----------------------------------------------------------------------------
// Role assignments
//
// Built-in roles:
//   Cognitive Services User                = a97b65f3-24c7-4388-baec-2e87135dc908 (read+invoke)
//   Cognitive Services OpenAI User         = 5e0bd9bd-7b93-4f28-af87-19fc36ad61bd (invoke OpenAI specifically)
// ----------------------------------------------------------------------------
var cognitiveServicesOpenAIUserRoleId = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'

resource functionAppOpenAIAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: openAiAccount
  name: guid(openAiAccount.id, functionAppPrincipalId, cognitiveServicesOpenAIUserRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesOpenAIUserRoleId)
    principalId: functionAppPrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource deployerOpenAIAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: openAiAccount
  name: guid(openAiAccount.id, deployerObjectId, cognitiveServicesOpenAIUserRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesOpenAIUserRoleId)
    principalId: deployerObjectId
    principalType: deployerPrincipalType
  }
}

// ----------------------------------------------------------------------------
// Outputs
// ----------------------------------------------------------------------------
output openAiAccountName string = openAiAccount.name
output openAiEndpoint string = openAiAccount.properties.endpoint
output gpt4oMiniDeploymentName string = gpt4oMiniDeployment.name
