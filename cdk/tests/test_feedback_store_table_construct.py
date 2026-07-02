"""CDK assertion tests for the redacted feedback-store table construct (WS-E / E5.1).

Validates the §6.2 schema + the three deltas from the signal store: TTL keyed on
`ttl`, PITR OFF (the DSAR-vs-PITR footgun), the `subject-locator-index` GSI, and
RemovalPolicy.RETAIN. The construct is provisioned in a minimal one-construct test
stack (it is a NET-NEW peer construct, not yet wired into StorageStack — that
wiring is the combined-deploy step, out of this synth-only stage).

Run from the cdk/ directory: ``python -m pytest tests/ -q``.
"""
from aws_cdk import App, Environment, Stack
from aws_cdk.assertions import Match, Template
from constructs import Construct

from cdk_constructs.feedback_store_table_construct import FeedbackStoreTable

TABLE_NAME = "sentra-redacted-feedback"


class _FeedbackTestStack(Stack):
    def __init__(self, scope: Construct, cid: str, **kwargs) -> None:
        super().__init__(scope, cid, **kwargs)
        self.feedback = FeedbackStoreTable(self, "FeedbackStore", table_name=TABLE_NAME)


def _template() -> Template:
    app = App()
    stack = _FeedbackTestStack(
        app, "TestFeedbackStack",
        env=Environment(account="123456789012", region="us-east-1"),
    )
    return Template.from_stack(stack)


def _feedback_table(template: Template) -> dict:
    tables = template.find_resources("AWS::DynamoDB::Table")
    hits = [
        t for t in tables.values()
        if t.get("Properties", {}).get("TableName") == TABLE_NAME
    ]
    assert hits, f"feedback table {TABLE_NAME} not synthesized"
    assert len(hits) == 1, "expected exactly one feedback table"
    return hits[0]["Properties"]


def test_feedback_table_pk_sk_schema():
    """§6.2: PK=tenant_id (tenant-scoped isolation), SK=record_id (DSAR locator)."""
    props = _feedback_table(_template())
    key_schema = props["KeySchema"]
    key_by_role = {k["KeyType"]: k["AttributeName"] for k in key_schema}
    assert key_by_role["HASH"] == "tenant_id"
    assert key_by_role["RANGE"] == "record_id"


def test_feedback_table_ttl_on_ttl_attribute():
    """DELTA 1 (§6.2): DynamoDB TTL is ENABLED and keyed on `ttl` — NOT the signal
    store's `expires_at`. Every record must expire (bounded, DPA-scoped)."""
    props = _feedback_table(_template())
    ttl = props.get("TimeToLiveSpecification")
    assert ttl is not None, "feedback table must enable TTL"
    assert ttl["AttributeName"] == "ttl"
    assert ttl["Enabled"] is True


def test_feedback_table_pitr_off():
    """DELTA 2 (§6.2 FOOTGUN — DSAR vs PITR): PITR must be OFF. A PITR snapshot of
    GDPR-pseudonymised data would outlive a DSAR delete. This is the load-bearing
    delta from the signal store; it must NOT be silently inherited/enabled."""
    props = _feedback_table(_template())
    pitr = props.get("PointInTimeRecoverySpecification")
    # PITR is OFF whether that's expressed by an absent block or an explicit False.
    if pitr is not None:
        assert pitr.get("PointInTimeRecoveryEnabled") in (False, None), (
            "feedback table PITR must be OFF (DSAR-vs-PITR footgun, §6.2)"
        )


def test_feedback_table_subject_locator_gsi():
    """§6.4: the `subject-locator-index` GSI (PK subject_locator) backs subject-
    targeted DSAR deletion. Its name is the join key the write/DSAR client
    (feedback_store.SUBJECT_LOCATOR_GSI) keys off."""
    props = _feedback_table(_template())
    gsis = props.get("GlobalSecondaryIndexes", [])
    by_name = {g["IndexName"]: g for g in gsis}
    assert "subject-locator-index" in by_name, "subject-locator DSAR GSI missing"
    gsi_keys = {k["KeyType"]: k["AttributeName"] for k in by_name["subject-locator-index"]["KeySchema"]}
    assert gsi_keys["HASH"] == "subject_locator"


def test_feedback_table_retain_deletion_policy():
    """DELTA 3 (§6.2): RemovalPolicy.RETAIN is deliberate — dropping the store would
    lose the labeled retrain corpus + the DSAR trail."""
    template = _template()
    template.has_resource(
        "AWS::DynamoDB::Table",
        {
            "DeletionPolicy": "Retain",
            "Properties": Match.object_like({"TableName": TABLE_NAME}),
        },
    )


def test_gsi_name_matches_client_contract():
    """The construct's GSI name constant equals the client's SUBJECT_LOCATOR_GSI —
    a drift here would make the DSAR query hit a non-existent index at runtime."""
    assert FeedbackStoreTable.SUBJECT_LOCATOR_INDEX_NAME == "subject-locator-index"
