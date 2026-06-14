"""Cloud Connections service — the Connect-Account wizard backend.

Implements `connections-api-spec.md` (kombai contract the console is built
against): create a connection, mint the confused-deputy `external_id`, let the
operator attach the cross-account role they deployed, then **test** it with a
live `sts:AssumeRole` + read-only probe before scanning.

Design
------
* **Born tenant-scoped** (feature §14.2): the table PK is `tenant_id`, SK is the
  connection `id`. There is no v1/v2 flag split — this is a net-new table, so it
  is tenant-scoped from creation. The tenant comes from the operator session
  (`tenancy.current_tenant()`), never the request body.
* **Reference, not secret** (feature §6 group F / §10.3): we store the customer's
  `role_arn` + scopes + our minted `external_id`. The credentials themselves are
  the customer's IAM role; we never hold a long-lived secret.
* **v1 = AWS only**: gcp/azure return `409 PROVIDER_NOT_AVAILABLE` on create.
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import boto3
from botocore.exceptions import ClientError

from app.config import settings
from app.utils import tenancy

logger = logging.getLogger(__name__)

# v1 supported providers. gcp/azure are spec'd but not wired (409 on create).
_SUPPORTED_PROVIDERS = {"aws"}
_ALL_PROVIDERS = {"aws", "gcp", "azure"}

# Least-privilege, read-only discovery scopes surfaced to the wizard so it can
# render the trust policy (feature §7 AWS row). Reference only — we don't grant
# these; the customer's role does.
# NOTE: Bedrock Agents management actions live under the `bedrock:` IAM prefix
# (NOT `bedrock-agent:` — that's only the boto3 client name). Using the wrong
# prefix yields a role that AssumeRole-succeeds but fails the ListAgents probe.
_PROVIDER_SCOPES = {
    "aws": [
        "bedrock:ListAgents",
        "bedrock:GetAgent",
        "bedrock:ListAgentActionGroups",
        "bedrock:GetAgentActionGroup",
        "bedrock:ListAgentAliases",
        "lambda:GetFunction",
    ],
    "gcp": ["aiplatform.reasoningEngines.list", "aiplatform.reasoningEngines.get"],
    "azure": ["Microsoft.CognitiveServices/accounts/read"],
}

_ROLE_ARN_RE = re.compile(r"^arn:aws:iam::\d{12}:role/.+")


class ConnectionError(Exception):
    """Base for connection-domain errors (mapped to HTTP in routes)."""


class ProviderNotAvailable(ConnectionError):
    """cloud_provider is valid but not wired in v1 (gcp/azure) → 409."""


class ConnectionNotFound(ConnectionError):
    """Unknown connection id → 404."""


class InvalidRoleArn(ConnectionError):
    """Malformed role ARN on PUT → 400."""


class NotConnected(ConnectionError):
    """Scan requested before the connection is tested/connected → 409."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class ConnectionsService:
    """DDB-backed cloud-connection store + live AssumeRole test."""

    def __init__(self):
        self.region = settings.aws_region
        self.dynamodb = boto3.resource("dynamodb", region_name=self.region)
        self._sts = None
        self._account_id: Optional[str] = None

    @property
    def table(self):
        # Always tenant-scoped (no flag): net-new table, born tenant-scoped.
        return self.dynamodb.Table(settings.dynamodb_connections_table)

    @property
    def discovery_cache_table(self):
        return self.dynamodb.Table(settings.dynamodb_discovery_cache_table)

    def _sts_client(self):
        if self._sts is None:
            self._sts = boto3.client("sts", region_name=self.region)
        return self._sts

    def _aegion_account_id(self) -> str:
        """Our own account id (for the trust-policy principal the customer adds).
        Resolved once via STS; falls back to a placeholder if STS is unreachable."""
        if self._account_id is None:
            try:
                self._account_id = self._sts_client().get_caller_identity()["Account"]
            except Exception:  # noqa: BLE001 - non-fatal; surface a usable default
                logger.warning("could not resolve Aegion account id from STS")
                self._account_id = "000000000000"
        return self._account_id

    # ------------------------------------------------------------------ shape
    def _to_api(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """Project a DDB item to the CloudConnection contract (spec §3).
        Never leaks tenant_id or internal attrs."""
        return {
            "id": item.get("id"),
            "cloud_provider": item.get("cloud_provider"),
            "status": item.get("status"),
            "account_ref": item.get("account_ref"),
            "external_id": item.get("external_id"),
            "aegion_principal_arn": item.get("aegion_principal_arn"),
            "role_arn": item.get("role_arn"),
            "scopes": item.get("scopes", []),
            "agents_visible": item.get("agents_visible"),
            "last_scan": item.get("last_scan"),
            "connected_at": item.get("connected_at"),
            "error": item.get("error"),
        }

    def _load(self, connection_id: str) -> Dict[str, Any]:
        item = self.table.get_item(
            Key={"tenant_id": tenancy.current_tenant(), "id": connection_id}
        ).get("Item")
        if not item:
            raise ConnectionNotFound(f"connection {connection_id} not found")
        return item

    # ------------------------------------------------------------------ reads
    def list_connections(self) -> Dict[str, Any]:
        """All connections for the current tenant (spec §4.1)."""
        from boto3.dynamodb.conditions import Key
        resp = self.table.query(
            KeyConditionExpression=Key("tenant_id").eq(tenancy.current_tenant())
        )
        return {"connections": [self._to_api(it) for it in resp.get("Items", [])]}

    def get_connection(self, connection_id: str) -> Dict[str, Any]:
        return self._to_api(self._load(connection_id))

    # ----------------------------------------------------------------- writes
    def create_connection(self, cloud_provider: str) -> Dict[str, Any]:
        """Create a connection + mint external_id so the wizard can render the
        trust policy before the role exists (spec §4.2)."""
        provider = (cloud_provider or "").lower()
        if provider not in _ALL_PROVIDERS:
            raise InvalidRoleArn(f"unknown cloud_provider {cloud_provider!r}")
        if provider not in _SUPPORTED_PROVIDERS:
            raise ProviderNotAvailable(f"{provider} connections are not available in v1")

        tenant = tenancy.current_tenant()
        connection_id = f"conn-{provider}-{uuid.uuid4().hex[:8]}"
        external_id = f"ext-{tenant}-{uuid.uuid4().hex[:12]}"
        item = {
            "tenant_id": tenant,
            "id": connection_id,
            "cloud_provider": provider,
            "status": "connecting",
            "account_ref": None,
            "external_id": external_id,
            "aegion_principal_arn": f"arn:aws:iam::{self._aegion_account_id()}:root",
            "role_arn": None,
            "scopes": _PROVIDER_SCOPES.get(provider, []),
            "agents_visible": None,
            "last_scan": None,
            "connected_at": None,
            "error": None,
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
        }
        self.table.put_item(Item=item)
        logger.info("created connection %s (provider=%s, tenant=%s)", connection_id, provider, tenant)
        return self._to_api(item)

    def set_role_arn(self, connection_id: str, role_arn: str) -> Dict[str, Any]:
        """Attach/replace the role reference after the operator deploys the stack
        (spec §4.4). Stays `connecting` until tested."""
        if not role_arn or not _ROLE_ARN_RE.match(role_arn):
            raise InvalidRoleArn(f"malformed role ARN: {role_arn!r}")
        item = self._load(connection_id)
        self.table.update_item(
            Key={"tenant_id": tenancy.current_tenant(), "id": connection_id},
            UpdateExpression="SET role_arn = :r, updated_at = :u",
            ExpressionAttributeValues={":r": role_arn, ":u": _now_iso()},
        )
        item["role_arn"] = role_arn
        return self._to_api(item)

    def delete_connection(self, connection_id: str) -> None:
        """Disconnect — drop the reference; imported agents are retained (spec §4.7)."""
        self._load(connection_id)  # 404 if missing
        self.table.delete_item(
            Key={"tenant_id": tenancy.current_tenant(), "id": connection_id}
        )
        logger.info("deleted connection %s", connection_id)

    # ------------------------------------------------------------- test / scan
    def test_connection(self, connection_id: str, role_arn: Optional[str] = None) -> Dict[str, Any]:
        """Live `sts:AssumeRole` with the stored external_id + a read-only probe
        (spec §4.5). Flips status connected/error. A rejected role is NOT an HTTP
        error — it returns `{ok:false, message}` so the wizard can show why."""
        item = self._load(connection_id)
        if role_arn:
            item = self.set_role_arn(connection_id, role_arn)  # convenience set+test
        role = item.get("role_arn")
        external_id = item.get("external_id")
        if not role:
            return {"ok": False, "agents_visible": None,
                    "message": "No role_arn set — deploy the trust stack and attach the role first."}

        ok, agents, message = self._assume_and_probe(role, external_id)
        agents_visible = len(agents) if agents is not None else None
        now = _now_iso()
        if ok:
            self.table.update_item(
                Key={"tenant_id": tenancy.current_tenant(), "id": connection_id},
                UpdateExpression=(
                    "SET #s = :s, connected_at = :c, agents_visible = :a, "
                    "#e = :e, updated_at = :u"
                ),
                ExpressionAttributeNames={"#s": "status", "#e": "error"},
                ExpressionAttributeValues={
                    ":s": "connected", ":c": now, ":a": agents_visible,
                    ":e": None, ":u": now,
                },
            )
        else:
            self.table.update_item(
                Key={"tenant_id": tenancy.current_tenant(), "id": connection_id},
                UpdateExpression="SET #s = :s, #e = :e, updated_at = :u",
                ExpressionAttributeNames={"#s": "status", "#e": "error"},
                ExpressionAttributeValues={":s": "error", ":e": message, ":u": now},
            )
        return {"ok": ok, "agents_visible": agents_visible, "message": message}

    def scan_connection(self, connection_id: str) -> Dict[str, Any]:
        """Trigger discovery for this connection (spec §4.6). 409 if not connected.

        Does a live `AssumeRole` + `ListAgents` and **persists** what it sees into
        the discovery cache (feature §8.1), so the Detected-Agents union reflects
        the real account. Returns the count it discovered."""
        item = self._load(connection_id)
        if item.get("status") != "connected":
            raise NotConnected(f"connection {connection_id} is {item.get('status')!r}, not connected")

        scan_id = f"scan-{uuid.uuid4().hex[:8]}"
        ok, agents, _msg = self._assume_and_probe(item.get("role_arn"), item.get("external_id"))
        discovered = self._persist_discovered(connection_id, item, agents) if ok and agents else 0
        agents_visible = len(agents) if agents is not None else item.get("agents_visible")
        self.table.update_item(
            Key={"tenant_id": tenancy.current_tenant(), "id": connection_id},
            UpdateExpression="SET last_scan = :l, agents_visible = :a, updated_at = :u",
            ExpressionAttributeValues={
                ":l": _now_iso(), ":a": agents_visible, ":u": _now_iso(),
            },
        )
        return {"scan_id": scan_id, "status": "scanning", "discovered_count": discovered}

    def _persist_discovered(self, connection_id: str, conn: Dict[str, Any],
                            agents: List[Dict[str, Any]]) -> int:
        """Write each scanned agent into the discovery cache (feature §8.1).
        Keyed by (tenant_id, native_resource_id); idempotent put (overwrite)."""
        tenant = tenancy.current_tenant()
        cloud = conn.get("cloud_provider", "aws")
        now = _now_iso()
        written = 0
        try:
            with self.discovery_cache_table.batch_writer() as batch:
                for a in agents:
                    native = a.get("native_resource_id")
                    if not native:
                        continue
                    batch.put_item(Item={
                        "tenant_id": tenant,
                        "native_resource_id": native,
                        "name": a.get("name") or native,
                        "cloud_provider": cloud,
                        "connection_id": connection_id,
                        "first_seen": now,
                        "last_scanned": now,
                    })
                    written += 1
        except ClientError:
            logger.exception("failed to persist discovered agents for %s", connection_id)
        return written

    def _assume_and_probe(self, role_arn: str, external_id: str):
        """AssumeRole(external_id) → bedrock-agent ListAgents.
        Returns (ok, agents|None, message) where `agents` is a list of
        ``{native_resource_id, name, status}``. Never raises — a rejected role is
        a normal, reportable outcome (spec §4.5)."""
        try:
            creds = self._sts_client().assume_role(
                RoleArn=role_arn,
                RoleSessionName="aegion-discovery-test",
                ExternalId=external_id,
                DurationSeconds=900,
            )["Credentials"]
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "AssumeRoleFailed")
            msg = exc.response.get("Error", {}).get("Message", str(exc))
            return False, None, f"{code}: {msg}"
        except Exception as exc:  # noqa: BLE001
            return False, None, f"AssumeRole failed: {exc}"

        try:
            bedrock = boto3.client(
                "bedrock-agent",
                region_name=self.region,
                aws_access_key_id=creds["AccessKeyId"],
                aws_secret_access_key=creds["SecretAccessKey"],
                aws_session_token=creds["SessionToken"],
            )
            agents: List[Dict[str, Any]] = []
            token = None
            while True:
                kwargs = {"maxResults": 100}
                if token:
                    kwargs["nextToken"] = token
                resp = bedrock.list_agents(**kwargs)
                for s in resp.get("agentSummaries", []):
                    agents.append({
                        "native_resource_id": s.get("agentId"),
                        "name": s.get("agentName"),
                        "status": s.get("agentStatus"),
                    })
                token = resp.get("nextToken")
                if not token:
                    break
            return True, agents, f"AssumeRole OK · {len(agents)} agents visible"
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "ListAgentsFailed")
            msg = exc.response.get("Error", {}).get("Message", str(exc))
            # Role assumed but scope insufficient — report honestly.
            return False, None, f"AssumeRole OK but probe failed — {code}: {msg}"
        except Exception as exc:  # noqa: BLE001
            return False, None, f"AssumeRole OK but probe failed: {exc}"
