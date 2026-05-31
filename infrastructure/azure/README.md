# AegionAI — Azure Cross-Cloud Demo (Workstream 15 M3)

This directory holds the Azure half of the cross-cloud demo: a Function App
that intercepts AI Foundry agent tool calls and forwards them to the AWS-side
Sentra security controller via API Gateway (LLD 16).

**Mirror of `cdk/` on the AWS side.** Single entry point: `azd up`.

## Layout

```
infrastructure/azure/
├── azure.yaml                      # azd project descriptor (services + hooks)
├── infra/
│   ├── main.bicep                  # subscription-scoped entry — creates RG + invokes modules
│   ├── main.parameters.json        # azd-managed env params
│   └── modules/
│       ├── function_app.bicep      # Function App + storage + plan + AppInsights
│       ├── key_vault.bicep         # Vault for Sentra API key
│       ├── key_vault_role.bicep    # MI access grant (Key Vault Secrets User)
│       ├── ai_foundry.bicep        # STUB (Task 3.1c)
│       └── agent.bicep             # STUB (Task 3.1c + 3.4)
├── scripts/
│   └── seed-api-key.sh             # postProvision hook (AWS Secrets Manager → Azure Key Vault)
└── README.md
```

## Prerequisites

```sh
# Authenticate AWS (Sentra API key lives in AWS Secrets Manager)
ada cred update --once --profile sentra

# Authenticate Azure
az login
az account set --subscription cb2512df-2001-45e1-aea6-88e80fc00299

# azd
brew install azd        # one-time
azd version             # confirm
```

Resource providers must be registered (one-time per subscription):

```sh
az provider register --namespace Microsoft.CognitiveServices --wait
az provider register --namespace Microsoft.MachineLearningServices --wait
az provider register --namespace Microsoft.Web --wait
az provider register --namespace Microsoft.KeyVault --wait
az provider register --namespace Microsoft.Storage --wait
az provider register --namespace Microsoft.Insights --wait
```

## Provision

```sh
cd infrastructure/azure

# First-time setup — creates a local azd env named "ws15-m3"
azd env new ws15-m3

# Dry-run plan (what-if)
azd provision --preview

# Provision infra AND publish Function source
azd up
```

`azd up`:
1. Runs Bicep to create the resource group, Function App, Storage, Key Vault.
2. Runs `scripts/seed-api-key.sh` (postProvision hook) to copy the Sentra API key
   from AWS Secrets Manager into the new Key Vault.
3. Publishes the Function source from
   `src/connectors/azure_foundry/azure_function/tool_interceptor/`
   (declared as a service in `azure.yaml`).

## Tear down (WS15 M6 demo-and-tear-down loop)

```sh
azd down --force --purge       # removes RG + purges Key Vault (avoids soft-delete name conflict on re-provision)
```

## Re-provision after teardown

Same `azd up` command. Resource names are deterministic via `uniqueString(rg.id, env)`,
so a fresh RG gives fresh names that won't collide with soft-deleted predecessors
(thanks to the `--purge` above).

## Smoke check after `azd up`

```sh
# Function App is up?
FUNC=$(azd env get-values | grep FUNCTION_APP_NAME | cut -d= -f2 | tr -d '"')
az functionapp show -n "$FUNC" -g aegionai-ws15-m3-rg --query 'state' -o tsv
# Expected: Running

# Sentra API key landed in Key Vault?
KV=$(azd env get-values | grep KEY_VAULT_NAME | cut -d= -f2 | tr -d '"')
az keyvault secret show --vault-name "$KV" --name sentra-api-key --query 'name' -o tsv
# Expected: sentra-api-key
```

## Operational notes

- **Region** is locked to `eastus2`. Free Trial has zero `gpt-4o-mini` quota in `eastus`.
- **Cost guard**: Function App is Consumption (Y1) plan — pay-per-invocation.
  Storage is LRS. Both fit comfortably inside the $200 Free Trial credit for the
  demo-and-tear-down window.
- **No custom `deploy.sh`.** Everything goes through `azd`. See
  [best-practices.md §11 Azure](../../best-practices.md#azure) for the rationale.
