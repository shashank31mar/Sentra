"""Cedar co-artifact storage convention (CT06c — the C6 root).

The **structured `AgentPolicyDocument` (`…/v{version}.yaml`) stays the stored
source of truth**; the compiled Cedar text is a *generated co-artifact* written
alongside it at the **same key with the extension swapped to `.cedar`**. There is
NO second metadata field for the Cedar key — `s3_key` keeps pointing at the
structured source and the `.cedar` key is derived by this convention (feature
§7.1). Consequences this guarantees:

  * `get_agent_policy` (shared loader, CT06) loads the structured source via
    `s3_key` and keeps every non-Cedar field — `allowed_callers`,
    `cross_cloud_dependencies`, `max_calls_per_minute` — which Cedar never sees.
  * `CedarPolicyEngine` (CT04) loads only the derived `.cedar` for evaluation.
  * Deleting or regenerating the `.cedar` can never lose structured fields,
    because the source object is independent and never overwritten by it.

`policy_format` on the metadata row records which form is authoritative for
evaluation: `yaml` (legacy / structured-only) vs `cedar` (a `.cedar` co-artifact
exists). The translator (CT08) flips it to `cedar` when it writes the co-artifact.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

# Metadata field + values describing which artifact form drives evaluation.
POLICY_FORMAT_FIELD = "policy_format"
FORMAT_YAML = "yaml"
FORMAT_CEDAR = "cedar"

CEDAR_EXT = ".cedar"
_SOURCE_EXTS = (".yaml", ".yml", ".json")


class CompiledPolicyNotFound(Exception):
    """No `.cedar` co-artifact exists at the derived key (policy not yet
    translated, or `policy_format` is still `yaml`). CT04 fails secure on this."""


def cedar_key_for(source_s3_key: str) -> str:
    """Derive the `.cedar` co-artifact key from the structured source key by
    swapping its extension. The source key itself is never altered."""
    root, ext = os.path.splitext(source_s3_key)
    if ext.lower() not in _SOURCE_EXTS:
        # Defensive: an unexpected source extension — append rather than mangle.
        logger.warning("Unexpected policy source extension on %s; appending %s", source_s3_key, CEDAR_EXT)
        return source_s3_key + CEDAR_EXT
    return root + CEDAR_EXT


def is_cedar_format(metadata: dict) -> bool:
    """True when the policy row declares a Cedar co-artifact is authoritative."""
    return (metadata or {}).get(POLICY_FORMAT_FIELD) == FORMAT_CEDAR


def load_compiled_policies(s3_client, bucket: str, source_s3_key: str) -> str:
    """Read the compiled Cedar text from the derived co-artifact key.

    Takes a boto3 S3 client (same pattern as the policy engine's reads) so it's
    trivially testable with moto. Raises CompiledPolicyNotFound when absent."""
    key = cedar_key_for(source_s3_key)
    try:
        obj = s3_client.get_object(Bucket=bucket, Key=key)
    except s3_client.exceptions.NoSuchKey as exc:
        raise CompiledPolicyNotFound(f"No compiled Cedar at s3://{bucket}/{key}") from exc
    return obj["Body"].read().decode("utf-8")


def put_compiled_policies(
    s3_client,
    bucket: str,
    source_s3_key: str,
    cedar_text: str,
    *,
    metadata: Optional[dict] = None,
) -> Optional[str]:
    """Write the compiled Cedar co-artifact next to the structured source.

    Used by the translator (CT08) and by CRUD when a policy is created/updated
    in Cedar form. Never touches the source object. Returns the S3 version id."""
    key = cedar_key_for(source_s3_key)
    resp = s3_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=cedar_text.encode("utf-8"),
        ContentType="text/plain; charset=utf-8",
        Metadata={k: str(v) for k, v in (metadata or {}).items()},
    )
    logger.info("Wrote compiled Cedar co-artifact s3://%s/%s", bucket, key)
    return resp.get("VersionId")
