"""WS-J — the hermetic in-process transport backing (J1.1).

The PR-gate runner is hermetic: NO real AWS, NO network, NO real PII. This module
stands up a moto AWS mock, seeds the minimal DynamoDB tables the controller's query
+ validate paths touch, and backs ``app.state.validation_service`` with a service
that runs the REAL ``DenyOverrides`` combiner over deterministic ``Signal``s — so a
canary ALLOW/DENY is a GENUINE combiner verdict (carrying ``metadata.winning_source``),
proving the wired ``POST /v1/validate`` → combiner → response seam (Invariant 3),
not a mocked always-ALLOW.

Why the real combiner and not the full Cedar pipeline: a genuine end-to-end ALLOW
requires a compiled Cedar artifact seeded in S3 (``cedar_enabled`` default is False →
the legacy floor fail-secure DENYs every request). Seeding a live Cedar bundle
in-process is heavy and flaky, which would itself violate the determinism invariant
(Invariant 5). Running the real ``DenyOverrides`` over deterministic Signals exercises
the SAME combiner code the production pipeline calls, deterministically — this is the
pattern the controller's own real-pipeline ``winning_source`` tests use. The
transport-parameterized ``live`` runner (Increment 2 / requires_live) exercises the
real Cedar pipeline against deployed prod.
"""
from __future__ import annotations

from typing import Dict, List

from app.api.models import ValidationRequest
from app.combiners import DenyOverrides, Signal, Source


# ---- deterministic Signal derivation (proves the combiner, not the detectors) ----
# A tiny, explicit rule set: an injection marker in user_input yields a sigma DENY
# Signal; everything else yields all-ALLOW Signals. The DECISION is produced by the
# REAL DenyOverrides combiner, not this function — this only supplies the frontier.
_INJECTION_MARKERS = (
    "ignore all previous instructions",
    "ignore previous instructions",
    "reveal the system prompt",
    "you are now dan",
)


def _derive_signals(request: ValidationRequest) -> List[Signal]:
    ui = (request.user_input or "").lower()
    tripped = any(m in ui for m in _INJECTION_MARKERS)
    signals = [
        Signal(source=Source.SENTRA_TRUST, decision="ALLOW", priority=90),
        Signal(source=Source.SENTRA_POLICY, decision="ALLOW", priority=80),
        Signal(source=Source.SENTRA_CROSS_AGENT, decision="ALLOW", priority=50),
    ]
    if tripped:
        signals.append(
            Signal(
                source=Source.SENTRA_SIGMA,
                decision="DENY",
                reason="prompt-injection signature matched",
                priority=70,
                threat_type="PROMPT_INJECTION",
                matched_rule="canary-injection-sentinel",
                severity="high",
            )
        )
    else:
        signals.append(Signal(source=Source.SENTRA_SIGMA, decision="ALLOW", priority=70))
    return signals


class _RealCombinerValidationService:
    """A drop-in ``validation_service`` whose ``validate_tool_call`` runs the REAL
    ``DenyOverrides`` combiner and maps its verdict to the ``/v1/validate`` response
    shape — surfacing ``metadata.winning_source`` so the canary can prove the
    combiner actually decided (not a short-circuit)."""

    def __init__(self) -> None:
        self._combiner = DenyOverrides()

    async def validate_tool_call(self, request: ValidationRequest) -> Dict:
        combined = self._combiner.combine(_derive_signals(request))
        winning_source = (combined.metadata or {}).get("winning_source")
        base = {
            "decision": combined.decision,
            "trust_score": 90.0,
            "session_id": request.session_id,
            "latency_ms": 1.0,
            # Surface the combiner attribution so J2 can assert the pipeline ran.
            "metadata": {"winning_source": winning_source},
        }
        if combined.decision == "DENY":
            base["reason"] = combined.reason or "combiner DENY"
            base["violation_type"] = combined.threat_type or "VALIDATION_FAILED"
            if combined.threat_type:
                base["threat_type"] = combined.threat_type
            if combined.matched_rule:
                base["matched_rule"] = combined.matched_rule
            if combined.severity:
                base["severity"] = combined.severity
        else:
            base["reason"] = "All validation checks passed"
            base["action_id"] = None
        return base


def _mk_bucket(s3, name: str, region: str) -> None:
    if region == "us-east-1":
        s3.create_bucket(Bucket=name)
    else:
        s3.create_bucket(
            Bucket=name, CreateBucketConfiguration={"LocationConstraint": region}
        )


def _seed_tables(region: str) -> None:
    """Create the DynamoDB tables the read/mutation routes touch (v1 / TENANCY_V2
    OFF schemas, mirroring the CDK) so a canary hits a REAL (empty) table → the
    documented 404/empty, never a 5xx from a missing table. Best-effort — a name
    the app doesn't use is harmless. Reuses ``mt_helpers.create_mt_tables`` for the
    tenancy set so the schema stays in one place."""
    import boto3
    from botocore.exceptions import ClientError

    from app.config import settings

    ddb = boto3.resource("dynamodb", region_name=region)

    def _mk(name, pk, sk=None, attrs=None, gsis=None):
        key = [{"AttributeName": pk, "KeyType": "HASH"}]
        adef = [{"AttributeName": pk, "AttributeType": "S"}]
        if sk:
            key.append({"AttributeName": sk, "KeyType": "RANGE"})
            adef.append({"AttributeName": sk, "AttributeType": "S"})
        for a in attrs or []:
            adef.append(a)
        kwargs = dict(TableName=name, KeySchema=key, AttributeDefinitions=adef,
                      BillingMode="PAY_PER_REQUEST")
        if gsis:
            kwargs["GlobalSecondaryIndexes"] = gsis
        try:
            ddb.create_table(**kwargs)
        except ClientError:
            pass

    # Tenancy set (tenants / tenant-members+GSI / agent-credentials+kid-index /
    # identity-fallback / platform-audit) — reuse the canonical helper.
    try:
        from tests.mt_helpers import create_mt_tables  # type: ignore

        create_mt_tables(ddb)
    except Exception:  # noqa: BLE001 — helper import optional; fall back below.
        _mk(settings.dynamodb_tenants_table, "tenant_id")
        _mk(settings.dynamodb_tenant_members_table, "operator_sub", "tenant_id",
            gsis=[{"IndexName": "tenant-members-index",
                   "KeySchema": [{"AttributeName": "tenant_id", "KeyType": "HASH"}],
                   "Projection": {"ProjectionType": "ALL"}}])

    # Core / v1 read+write tables (schemas mirror the CDK; TENANCY_V2 OFF default).
    _mk(settings.dynamodb_session_table, "session_id")
    _mk(settings.dynamodb_agent_registry_table, "agent_id")
    _mk(settings.dynamodb_tool_registry_table, "tool_id")
    _mk(settings.dynamodb_policies_metadata_table, "policy_id",
        attrs=[{"AttributeName": "agent_id", "AttributeType": "S"},
               {"AttributeName": "status", "AttributeType": "S"}],
        gsis=[{"IndexName": "agent-index",
               "KeySchema": [{"AttributeName": "agent_id", "KeyType": "HASH"}],
               "Projection": {"ProjectionType": "ALL"}},
              {"IndexName": "status-index",
               "KeySchema": [{"AttributeName": "status", "KeyType": "HASH"}],
               "Projection": {"ProjectionType": "ALL"}}])
    _mk(settings.dynamodb_sigma_rules_metadata_table, "rule_id",
        attrs=[{"AttributeName": "status", "AttributeType": "S"}],
        gsis=[{"IndexName": "status-index",
               "KeySchema": [{"AttributeName": "status", "KeyType": "HASH"}],
               "Projection": {"ProjectionType": "ALL"}}])
    _mk(settings.dynamodb_connections_table, "tenant_id", "id")
    _mk(settings.dynamodb_discovery_cache_table, "tenant_id", "native_resource_id")
    _mk(settings.dynamodb_quota_counters_table, "tenant_id", "window")
    _mk(settings.dynamodb_feedback_store_table, "tenant_id", "subject_locator")
    _mk(settings.dynamodb_validation_signals_table, "session_id", "sk",
        attrs=[{"AttributeName": "agent_id", "AttributeType": "S"},
               {"AttributeName": "timestamp_ms", "AttributeType": "N"}],
        gsis=[{"IndexName": "agent-timestamp-index",
               "KeySchema": [{"AttributeName": "agent_id", "KeyType": "HASH"},
                             {"AttributeName": "timestamp_ms", "KeyType": "RANGE"}],
               "Projection": {"ProjectionType": "ALL"}}])


def build_inprocess_client():
    """Generator (fixture body): enter moto, seed tables, back the app with the
    real-combiner service, yield a ``CanaryClient``, then tear the mock down."""
    from moto import mock_aws

    from canary.conftest import CanaryClient

    mock = mock_aws()
    mock.start()
    try:
        from app.config import settings

        region = settings.aws_region
        _seed_tables(region)

        from fastapi.testclient import TestClient

        from app.main import app

        # Back the app BEFORE entering the TestClient context so lifespan's
        # ValidationService() build is superseded on first request.
        client_cm = TestClient(app)
        with client_cm as tc:
            prev = getattr(app.state, "validation_service", None)
            app.state.validation_service = _RealCombinerValidationService()
            try:
                yield CanaryClient(tc, mode="inprocess")
            finally:
                app.state.validation_service = prev
    finally:
        mock.stop()
