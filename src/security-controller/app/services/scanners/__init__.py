"""Per-cloud discovery scanner adapters (feature §12).

Each adapter lists the AI agents running in a connected customer account and
maps them to the Import Record shape (feature §6). The AWS path lives inline in
``connections_service`` (pure boto3); non-AWS clouds get a dedicated adapter
here because they pull in cloud-specific SDKs that are lazy-imported so the
controller boots without them.
"""

from .azure_scanner import AzureDiscoveryError, AzureScanner

__all__ = ["AzureScanner", "AzureDiscoveryError"]
