"""Create + bulk-load the demo-owned DynamoDB tables (LLD 22 §8.1).

Self-contained: these tables are provisioned by the demo, NOT by core ``cdk/stacks/storage_stack.py``
(separation, LLD 22 §3). All tables are on-demand (PAY_PER_REQUEST) and tagged so they're easy to
find and tear down. Loaders use the ``sentra`` profile locally; the agents read them at runtime via
``common/store.py`` with role creds.
"""
from __future__ import annotations

import os
from decimal import Decimal
from typing import Any, Dict, List

DEFAULT_PROFILE = os.environ.get("AWS_PROFILE", "sentra")
DEFAULT_REGION = os.environ.get("AWS_REGION", "us-east-1")

TAGS = [{"Key": "project", "Value": "sentra-demo-agents"}, {"Key": "workstream", "Value": "WS-23"}]


def _resource(profile: str = DEFAULT_PROFILE, region: str = DEFAULT_REGION):
    import boto3

    return boto3.Session(profile_name=profile, region_name=region).resource("dynamodb")


def _to_ddb(value: Any) -> Any:
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {k: _to_ddb(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_ddb(v) for v in value]
    return value


def ensure_table(ddb, name: str, key_schema: List[Dict], attr_defs: List[Dict]) -> None:
    """Create an on-demand table if it doesn't exist; wait until ACTIVE. Idempotent."""
    existing = {t.name for t in ddb.tables.all()}
    if name in existing:
        print(f"  • table {name} already exists")
        return
    print(f"  + creating table {name} ...")
    table = ddb.create_table(
        TableName=name,
        KeySchema=key_schema,
        AttributeDefinitions=attr_defs,
        BillingMode="PAY_PER_REQUEST",
        Tags=TAGS,
    )
    table.wait_until_exists()
    print(f"  ✓ {name} ACTIVE")


def bulk_put(ddb, name: str, items: List[Dict[str, Any]]) -> int:
    table = ddb.Table(name)
    with table.batch_writer() as batch:
        for item in items:
            batch.put_item(Item=_to_ddb(item))
    print(f"  ✓ wrote {len(items)} items to {name}")
    return len(items)
