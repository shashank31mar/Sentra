"""
S3 Policy Store - Upload/download/version management for policy YAML files.
"""
import boto3
import logging
from typing import Optional, Dict
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


class S3PolicyStore:
    """Manages policy content storage in S3 with versioning."""

    def __init__(self, bucket_name: str = "sentra-mvp-artifacts"):
        self.s3_client = boto3.client('s3')
        self.bucket_name = bucket_name

    async def upload(
        self,
        key: str,
        content: str,
        metadata: Optional[Dict[str, str]] = None
    ) -> str:
        """
        Upload policy YAML content to S3.

        Args:
            key: S3 object key (e.g., "policies/agents/customer-query-agent/v1.0.0.yaml")
            content: YAML content as string
            metadata: Optional metadata dict

        Returns:
            S3 version ID (for versioned buckets)

        Raises:
            S3UploadException if upload fails
        """
        try:
            response = self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=key,
                Body=content.encode('utf-8'),
                ContentType='application/x-yaml',
                Metadata=metadata or {}
            )

            version_id = response.get('VersionId', 'null')
            logger.info(f"Uploaded policy to s3://{self.bucket_name}/{key} (version: {version_id})")
            return version_id

        except ClientError as e:
            logger.error(f"Failed to upload policy to S3: {e}")
            raise S3UploadException(f"S3 upload failed: {e}")

    async def download(
        self,
        key: str,
        version_id: Optional[str] = None
    ) -> str:
        """
        Download policy YAML content from S3.

        Args:
            key: S3 object key
            version_id: Optional S3 version ID (if None, gets latest)

        Returns:
            YAML content as string

        Raises:
            S3DownloadException if download fails
        """
        try:
            params = {
                'Bucket': self.bucket_name,
                'Key': key
            }
            if version_id:
                params['VersionId'] = version_id

            response = self.s3_client.get_object(**params)
            content = response['Body'].read().decode('utf-8')

            logger.info(f"Downloaded policy from s3://{self.bucket_name}/{key} (version: {version_id or 'latest'})")
            return content

        except ClientError as e:
            if e.response['Error']['Code'] == 'NoSuchKey':
                logger.error(f"Policy not found in S3: {key}")
                raise PolicyNotFoundException(f"Policy not found: {key}")
            else:
                logger.error(f"Failed to download policy from S3: {e}")
                raise S3DownloadException(f"S3 download failed: {e}")

    async def list_versions(self, key: str) -> list:
        """
        List all versions of a policy object.

        Args:
            key: S3 object key

        Returns:
            List of version dicts with VersionId, LastModified, Size
        """
        try:
            response = self.s3_client.list_object_versions(
                Bucket=self.bucket_name,
                Prefix=key
            )

            versions = response.get('Versions', [])
            return [
                {
                    'version_id': v['VersionId'],
                    'last_modified': v['LastModified'].isoformat(),
                    'size': v['Size'],
                    'is_latest': v['IsLatest']
                }
                for v in versions
            ]

        except ClientError as e:
            logger.error(f"Failed to list versions for {key}: {e}")
            return []

    async def delete(self, key: str, version_id: Optional[str] = None):
        """
        Delete a policy object or specific version.

        Args:
            key: S3 object key
            version_id: Optional version ID (if None, deletes latest)

        Note: For soft delete workflow, this is rarely used.
              Policies are marked disabled in DynamoDB but kept in S3.
        """
        try:
            params = {
                'Bucket': self.bucket_name,
                'Key': key
            }
            if version_id:
                params['VersionId'] = version_id

            self.s3_client.delete_object(**params)
            logger.info(f"Deleted policy from s3://{self.bucket_name}/{key} (version: {version_id or 'latest'})")

        except ClientError as e:
            logger.error(f"Failed to delete policy from S3: {e}")
            raise S3DeleteException(f"S3 delete failed: {e}")


class S3UploadException(Exception):
    """Raised when S3 upload fails."""
    pass


class S3DownloadException(Exception):
    """Raised when S3 download fails."""
    pass


class S3DeleteException(Exception):
    """Raised when S3 delete fails."""
    pass


class PolicyNotFoundException(Exception):
    """Raised when policy not found in S3."""
    pass
