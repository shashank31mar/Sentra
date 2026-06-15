import { IconBrandAws, IconBrandAzure, IconBrandGoogle, type Icon } from '@tabler/icons-react'
import type { CloudProvider } from '../../types/enums'

export interface CloudOption {
  provider: CloudProvider
  name: string
  detail: string
  icon: Icon
  color: string
  available: boolean
}

/** Provider rollout order (feature.md §10.6): AWS + Azure live, GCP fast-follow. */
export const CLOUD_OPTIONS: CloudOption[] = [
  { provider: 'aws', name: 'AWS Bedrock', detail: 'Agents + action groups', icon: IconBrandAws, color: '#FF9900', available: true },
  { provider: 'azure', name: 'Azure AI Foundry', detail: 'OpenAI deployments + agents', icon: IconBrandAzure, color: '#37A0E8', available: true },
  { provider: 'gcp', name: 'GCP Vertex AI', detail: 'Reasoning Engine', icon: IconBrandGoogle, color: '#4285F4', available: false },
]

/** Default Azure read-only scopes for the reassurance panel (mirrors the SP roles). */
export const AZURE_DEFAULT_SCOPES = [
  'Microsoft.CognitiveServices/accounts/read',
  'Microsoft.CognitiveServices/accounts/deployments/read',
]

/**
 * Render the Azure setup as copyable `az` commands (the Azure analog of the AWS
 * CloudFormation role). Creates a read-only service principal — Reader (mgmt:
 * list Cognitive Services accounts + deployments) + Cognitive Services User
 * (data-plane: list AI Foundry agents). The operator pastes the resulting
 * subscription/tenant/client ids + the vault secret name back into the console.
 */
export function buildAzureSetup(): string {
  return `# 1) Create a read-only discovery service principal on your subscription
SUB=$(az account show --query id -o tsv)
az ad sp create-for-rbac --name "aegion-discovery-sp" --role Reader --scopes "/subscriptions/$SUB"
# note the appId (= client_id), password (= client secret), and tenant from the output

# 2) Allow listing AI Foundry agents (read-only data-plane)
az role assignment create --assignee <appId> --role "Cognitive Services User" --scope "/subscriptions/$SUB"

# 3) Store the secret in your vault; the console keeps a REFERENCE only
aws secretsmanager create-secret --name "aegion/azure/discovery-sp" \\
  --secret-string '{"client_secret":"<password>"}'`
}

/**
 * Render the cross-account IAM role as a deployable CloudFormation template.
 * The `ExternalId` condition blocks the confused-deputy attack (feature.md §7,
 * connections-api-spec §3); scopes are least-privilege read-only.
 */
export function buildRoleTemplate(params: {
  externalId: string
  principalArn: string
  scopes: string[]
}): string {
  const actions = params.scopes.map((s) => `                  - ${s}`).join('\n')
  return `Resources:
  AegionDiscoveryRole:
    Type: AWS::IAM::Role
    Properties:
      RoleName: AegionDiscoveryRole
      AssumeRolePolicyDocument:
        Version: "2012-10-17"
        Statement:
          - Effect: Allow
            Principal:
              AWS: "${params.principalArn}"
            Action: sts:AssumeRole
            Condition:
              StringEquals:
                sts:ExternalId: "${params.externalId}"
      Policies:
        - PolicyName: AegionReadOnly
          PolicyDocument:
            Version: "2012-10-17"
            Statement:
              - Effect: Allow
                Action:
${actions}
                Resource: "*"
Outputs:
  RoleArn:
    Description: Paste this ARN back into the Aegion console
    Value: !GetAtt AegionDiscoveryRole.Arn`
}
