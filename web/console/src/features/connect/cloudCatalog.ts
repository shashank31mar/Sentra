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

/** Provider rollout order (feature.md §10.6): AWS first, Azure/GCP fast-follow. */
export const CLOUD_OPTIONS: CloudOption[] = [
  { provider: 'aws', name: 'AWS Bedrock', detail: 'Agents + action groups', icon: IconBrandAws, color: '#FF9900', available: true },
  { provider: 'azure', name: 'Azure AI Foundry', detail: 'Functions + AI projects', icon: IconBrandAzure, color: '#37A0E8', available: false },
  { provider: 'gcp', name: 'GCP Vertex AI', detail: 'Reasoning Engine', icon: IconBrandGoogle, color: '#4285F4', available: false },
]

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
