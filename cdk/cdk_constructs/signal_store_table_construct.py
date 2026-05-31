"""Reusable DynamoDB construct for the Validation Signal Store.

Provisions the `sentra-validation-signals` table that backs LLD 17's
multi-signal substrate. Schema details and rationale live in
[lld/17-validation-signal-store.md §5.2](../../lld/17-validation-signal-store.md#52-ddb-schema--sentra-validation-signals).

Why a construct (not inline in storage_stack.py)
-------------------------------------------------
Per `best-practices.md` §1/§3, persistent storage with composite keys plus
multiple GSIs is the canonical "extract to a construct" case — the table is
also referenced by the controller's IAM grant in compute_stack.py and the
test suite, so a single owner of the schema definition prevents drift.
"""

from aws_cdk import (
    RemovalPolicy,
    aws_dynamodb as dynamodb,
)
from constructs import Construct


class ValidationSignalStoreTable(Construct):
    """DynamoDB table for per-validator signal storage with two GSIs.

    Attributes:
        table: the underlying `dynamodb.Table` for downstream IAM grants
               and CfnOutput wiring.
    """

    AGENT_INDEX_NAME = "agent-timestamp-index"
    DECISION_DATE_INDEX_NAME = "decision-date-timestamp-index"

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        table_name: str,
    ) -> None:
        super().__init__(scope, construct_id)

        # Main table — PK=session_id, SK=request_id#timestamp_ms#source.
        # SK leads with request_id (not timestamp) so per-request lookups are
        # an O(K) Query(SK begins_with <rid>) rather than a FilterExpression
        # over the full session partition. See LLD 17 §5.2 SK rationale.
        self.table = dynamodb.Table(
            self,
            "Table",
            table_name=table_name,
            partition_key=dynamodb.Attribute(
                name="session_id",
                type=dynamodb.AttributeType.STRING,
            ),
            sort_key=dynamodb.Attribute(
                name="sk",
                type=dynamodb.AttributeType.STRING,
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            time_to_live_attribute="expires_at",
            removal_policy=RemovalPolicy.RETAIN,
            point_in_time_recovery=False,
        )

        # GSI 1: agent-scoped lookup. Used by future agent-detail panels
        # that want "every decision for this agent in the last hour".
        self.table.add_global_secondary_index(
            index_name=self.AGENT_INDEX_NAME,
            partition_key=dynamodb.Attribute(
                name="agent_id",
                type=dynamodb.AttributeType.STRING,
            ),
            sort_key=dynamodb.Attribute(
                name="timestamp_ms",
                type=dynamodb.AttributeType.NUMBER,
            ),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        # GSI 2: paginated time-range scan across all sessions. Backs
        # GET /v1/decisions. `decision_date` is a writer-populated attribute
        # (YYYY-MM-DD slice of timestamp_iso) — not a derived expression,
        # because DDB GSIs project from real attributes only.
        self.table.add_global_secondary_index(
            index_name=self.DECISION_DATE_INDEX_NAME,
            partition_key=dynamodb.Attribute(
                name="decision_date",
                type=dynamodb.AttributeType.STRING,
            ),
            sort_key=dynamodb.Attribute(
                name="timestamp_ms",
                type=dynamodb.AttributeType.NUMBER,
            ),
            projection_type=dynamodb.ProjectionType.ALL,
        )

    @property
    def table_name(self) -> str:
        return self.table.table_name

    @property
    def table_arn(self) -> str:
        return self.table.table_arn
