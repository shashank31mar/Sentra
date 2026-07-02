"""Reusable DynamoDB construct for the opt-in REDACTED feedback store (WS-E / E5.1).

Provisions the `sentra-redacted-feedback` table that backs LLD 29 §6 — a SEPARATE,
tenant-scoped store of REDACTED-only records, bounded TTL, opt-in per DPA, that
feeds the offline re-score + retrain loop (FR-3.14). It is NOT the signal store
(LLD 17) and NOT the meter/billing ledger (WS-H); conflating them is a consent
breach (§6.1). The write / eval-gate / DSAR client is
[src/security-controller/app/redaction/feedback_store.py] (stage 2) — this
construct provisions the table that client's contract targets.

Anchored on
[signal_store_table_construct.py](signal_store_table_construct.py) for shape, with
the three deltas that matter for a store of redacted-but-still-personal data
(LLD 29 §6.2):

  * **TTL on `ttl`** (the signal store keys TTL off `expires_at`): every feedback
    record MUST expire — bounded, DPA-scoped (default 90 days; owner/counsel set
    the final value). Never indefinite retention.
  * **PITR default OFF** (`point_in_time_recovery=False`) — this is NOT inherited
    silently from the signal store; it is deliberate. For a store holding
    GDPR-pseudonymised (still personal) data, a continuous PITR backup would
    RETAIN a DSAR-deleted subject's record PAST the deletion, undermining §6.4.
    PITR must be OFF (or DSAR-scoped) here (§6.2 FOOTGUN).
  * **`subject_locator` GSI** — the join key for per-subject GDPR DSAR targeted
    deletion (§6.4). `HMAC(per-tenant-salt, subject_key)` is written before
    masking where a stable subject key exists; null → the record is TTL-only
    deletable.

`RemovalPolicy.RETAIN` is kept deliberate (losing the store would drop labeled
retrain traffic + the DSAR trail); it is not an accident of copy-paste.
"""

from aws_cdk import (
    RemovalPolicy,
    aws_dynamodb as dynamodb,
)
from constructs import Construct


class FeedbackStoreTable(Construct):
    """DynamoDB table for the opt-in redacted feedback store (LLD 29 §6.2).

    Attributes:
        table: the underlying `dynamodb.Table` for downstream IAM grants,
               CfnOutput wiring, and the controller's task-role grant.
    """

    # The subject-locator GSI backs the DSAR targeted-delete path (§6.4). The name
    # is the join key the write/DSAR client keys off (feedback_store.py
    # SUBJECT_LOCATOR_GSI) and the moto tests create under — keep it in one place.
    SUBJECT_LOCATOR_INDEX_NAME = "subject-locator-index"

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        table_name: str,
    ) -> None:
        """Provision the redacted feedback-store table.

        Args:
            table_name: physical DDB table name (default `sentra-redacted-feedback`,
                mirrors ``config.py`` ``dynamodb_feedback_store_table``).
        """
        super().__init__(scope, construct_id)

        # Main table — PK=tenant_id (tenant-scoped isolation, never cross-tenant
        # readable, NFR-6), SK=record_id (`{ms}#{uuid}` — also the DSAR record
        # locator, §6.4). A tenant Query() PK-scoped to tenant_id is the natural
        # isolation boundary; a subject-targeted delete uses the GSI below.
        self.table = dynamodb.Table(
            self,
            "Table",
            table_name=table_name,
            partition_key=dynamodb.Attribute(
                name="tenant_id",
                type=dynamodb.AttributeType.STRING,
            ),
            sort_key=dynamodb.Attribute(
                name="record_id",
                type=dynamodb.AttributeType.STRING,
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            # DELTA 1 — TTL keyed off `ttl` (the signal store uses `expires_at`).
            # Every record must expire (bounded, DPA-scoped); never indefinite.
            time_to_live_attribute="ttl",
            # DELTA 2 — PITR default OFF, DELIBERATE (NOT inherited from the signal
            # store). A PITR snapshot of GDPR-pseudonymised data would OUTLIVE a
            # DSAR delete (§6.2 / §6.4 FOOTGUN). Do not turn this on without also
            # scoping the DSAR procedure to the PITR window.
            point_in_time_recovery=False,
            # DELTA 3 — RETAIN kept deliberate: dropping the store would lose the
            # labeled retrain corpus + the DSAR-deletion trail.
            removal_policy=RemovalPolicy.RETAIN,
        )

        # GSI — subject-targeted DSAR deletion (§6.4). PK is the pseudonymous
        # `subject_locator` (`HMAC(per-tenant-salt, subject_key)`), so a DSAR
        # `DELETE /v1/feedback/subjects/{subject_locator}` finds every record for a
        # subject without a full scan. Records with no stable subject key carry no
        # `subject_locator` (TTL-only-deletable) and are simply absent from the GSI.
        # ALL projection so the DSAR delete reads the base keys (tenant_id,
        # record_id) it must batch-delete off the index page.
        self.table.add_global_secondary_index(
            index_name=self.SUBJECT_LOCATOR_INDEX_NAME,
            partition_key=dynamodb.Attribute(
                name="subject_locator",
                type=dynamodb.AttributeType.STRING,
            ),
            projection_type=dynamodb.ProjectionType.ALL,
        )

    @property
    def table_name(self) -> str:
        return self.table.table_name

    @property
    def table_arn(self) -> str:
        return self.table.table_arn
