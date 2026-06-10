"""Runtime data access for the demo tools — dual backend (in-memory or DynamoDB).

Tools call these functions; they never talk to a database directly. The backend is chosen by env:

    AEGION_DEMO_BACKEND = "memory" (default)  -> the deterministic datagen snapshot (offline/tests)
                        = "ddb"               -> real DynamoDB tables (Lambda / Azure Function)

Table names come from env (with sane defaults) so nothing is hard-coded (best-practices §2). The
in-memory path makes every tool unit-testable with no AWS, while the DDB path is what runs in the
deployed payments agent after ``load_bank_data.py`` seeds the bank tables.

Fraud scoring is deterministic (a stand-in for an IEEE-CIS-trained model) so demo decisions are
reproducible.
"""
from __future__ import annotations

import hashlib
import os
import uuid
from decimal import Decimal
from typing import Any, Dict, List, Optional

from . import datagen

ENV_BACKEND = "AEGION_DEMO_BACKEND"
ENV_ACCOUNTS = "ACME_ACCOUNTS_TABLE"
ENV_TXNS = "ACME_TXNS_TABLE"

DEFAULT_ACCOUNTS_TABLE = "acme-bank-accounts"
DEFAULT_TXNS_TABLE = "acme-bank-transactions"

# NOTE: this store backs the AWS payments agent (real DynamoDB) and the identity agent's fraud score.
# The Azure identity/telecom agents are deterministic/pure at runtime (see identity_core.py /
# telecom_core.py) to keep their Function packages stdlib-only — they do NOT read a subscriber table.


class NotFound(Exception):
    """A requested account/subscriber does not exist (tools map this to a clean error)."""


# --------------------------------------------------------------------------- backend selection
def _use_ddb() -> bool:
    return os.environ.get(ENV_BACKEND, "memory").lower() == "ddb"


def _table(env_name: str, default: str):
    import boto3  # imported lazily so the in-memory path needs no boto3

    name = os.environ.get(env_name, default)
    return boto3.resource("dynamodb").Table(name)


def _to_ddb(value: Any) -> Any:
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {k: _to_ddb(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_ddb(v) for v in value]
    return value


def _from_ddb(value: Any) -> Any:
    if isinstance(value, Decimal):
        f = float(value)
        return int(f) if f.is_integer() else f
    if isinstance(value, dict):
        return {k: _from_ddb(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_from_ddb(v) for v in value]
    return value


# --------------------------------------------------------------------------- fraud scoring
def fraud_score(key: str) -> Dict[str, Any]:
    """Fraud score in [0,1] + risk band for a key.

    Grounded in the real IEEE-CIS dataset when the derived snapshot is bundled (the score is the
    empirical fraud rate of the key's transaction cohort; see ``realdata`` + ``data-pipelines``).
    Falls back to a deterministic hash stand-in if the snapshot isn't present, so the demo never
    hard-fails on missing data.
    """
    from . import realdata

    record = realdata.fraud_record(key)
    if record is not None:
        return {"fraud_score": record["fraud_score"], "risk": record["risk"],
                "is_fraud": record["is_fraud"], "source": "ieee_cis"}

    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    score = (int(digest[:8], 16) % 1000) / 1000.0
    risk = "high" if score >= 0.8 else "med" if score >= 0.5 else "low"
    return {"fraud_score": round(score, 3), "risk": risk, "source": "synthetic"}


# --------------------------------------------------------------------------- accounts / payments
def get_account(account_id: str) -> Dict[str, Any]:
    if _use_ddb():
        item = _table(ENV_ACCOUNTS, DEFAULT_ACCOUNTS_TABLE).get_item(Key={"account_id": account_id}).get("Item")
        if not item:
            raise NotFound(f"account {account_id} not found")
        return _from_ddb(item)
    acct = datagen.default_dataset().accounts.get(account_id)
    if not acct:
        raise NotFound(f"account {account_id} not found")
    return dict(acct)


def get_transactions(account_id: str, limit: int = 10) -> List[Dict[str, Any]]:
    limit = max(1, min(int(limit or 10), 100))
    if _use_ddb():
        from boto3.dynamodb.conditions import Key

        resp = _table(ENV_TXNS, DEFAULT_TXNS_TABLE).query(
            KeyConditionExpression=Key("account_id").eq(account_id),
            ScanIndexForward=False,
            Limit=limit,
        )
        return [_from_ddb(i) for i in resp.get("Items", [])]
    txns = datagen.default_dataset().transactions.get(account_id, [])
    return [dict(t) for t in txns[:limit]]


def process_refund(account_id: str, amount: float, txn_id: Optional[str] = None) -> Dict[str, Any]:
    """Credit a refund to the account. (Core enforces the $5000 limit upstream, LLD 22 §6.5.)"""
    amount = float(amount)
    acct = get_account(account_id)
    new_balance = round(float(acct["balance"]) + amount, 2)
    refund_id = f"rfnd-{uuid.uuid4().hex[:12]}"
    if _use_ddb():
        _table(ENV_ACCOUNTS, DEFAULT_ACCOUNTS_TABLE).update_item(
            Key={"account_id": account_id},
            UpdateExpression="SET balance = :b",
            ExpressionAttributeValues={":b": _to_ddb(new_balance)},
        )
    else:
        datagen.default_dataset().accounts[account_id]["balance"] = new_balance
    return {"success": True, "refund_id": refund_id, "new_balance": new_balance, "txn_id": txn_id}


def transfer_funds(from_account: str, to_account: str, amount: float) -> Dict[str, Any]:
    """Move funds out of an account. NOTE: core does not enforce a transfer limit (LLD 22 §6.5)."""
    amount = float(amount)
    acct = get_account(from_account)
    new_balance = round(float(acct["balance"]) - amount, 2)
    transfer_id = f"xfer-{uuid.uuid4().hex[:12]}"
    if _use_ddb():
        _table(ENV_ACCOUNTS, DEFAULT_ACCOUNTS_TABLE).update_item(
            Key={"account_id": from_account},
            UpdateExpression="SET balance = :b",
            ExpressionAttributeValues={":b": _to_ddb(new_balance)},
        )
    else:
        datagen.default_dataset().accounts[from_account]["balance"] = new_balance
    return {"success": True, "transfer_id": transfer_id, "from_account": from_account,
            "to_account": to_account, "amount": amount, "new_balance": new_balance}


# --------------------------------------------------------------------------- fraud (identity agent)
def check_fraud_score(key: str) -> Dict[str, Any]:
    return {"key": key, **fraud_score(key)}

# Telecom/identity tool behavior (verify_identity, lookup_subscriber, change_plan, reset_sim,
# port_out_number) lives in the Azure agents themselves (identity_core.py / telecom_core.py) as
# deterministic pure functions, so those Function packages stay stdlib-only. There is intentionally
# no subscriber datastore path here (Kiro review #3/#4).
