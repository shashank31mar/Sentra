"""Deterministic, linked synthetic dataset for the demo agents (LLD 22 §8.3).

Shaped like the public datasets the demo cites:
  * accounts / transactions  -> PaySim (mobile-money, fraud-labelled)
  * subscribers              -> IBM Telco Customer Churn (+ Faker operational layer)
  * fraud features           -> IEEE-CIS (deterministic score in fraud_lookup.py)

Everything is generated from a fixed seed so the same data appears on every run and across both
clouds — which matters because the cross-cloud scenarios link a bank account to a telecom subscriber.
Only synthetic rows are produced here; drop real CSVs in ``data/raw/`` to enrich (loaders handle it).

This module has a single hard dependency (``faker``) and is pure-Python so it runs offline, in tests,
and inside the data loaders alike.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

try:
    from faker import Faker
except ImportError:  # pragma: no cover - faker is in requirements.txt
    Faker = None  # type: ignore

# PaySim transaction types.
_TXN_TYPES = ("PAYMENT", "TRANSFER", "CASH_OUT", "DEBIT", "CASH_IN")
# IBM-Telco-style plan tiers.
_PLANS = ("prepaid-basic", "postpaid-standard", "postpaid-plus", "fiber-1gbps", "family-share")
_CARRIERS = ("Verizon", "T-Mobile", "AT&T", "Mint", "Google Fi")


@dataclass
class Dataset:
    """An in-memory, mutable snapshot of the demo's backing data."""

    accounts: Dict[str, dict] = field(default_factory=dict)          # account_id -> account
    transactions: Dict[str, List[dict]] = field(default_factory=dict)  # account_id -> [txn, ...]
    subscribers: Dict[str, dict] = field(default_factory=dict)       # msisdn -> subscriber

    def account_by_msisdn(self, msisdn: str) -> Optional[dict]:
        sub = self.subscribers.get(msisdn)
        if not sub:
            return None
        return self.accounts.get(sub.get("account_id"))


def _mask_ssn(rng: random.Random) -> str:
    return f"***-**-{rng.randint(1000, 9999)}"


def _msisdn(rng: random.Random) -> str:
    # +1 NANP-ish, avoiding leading 0/1 in area/exchange.
    return f"+1{rng.randint(200, 989)}{rng.randint(200, 989)}{rng.randint(1000, 9999)}"


def generate_dataset(
    *,
    seed: int = 42,
    n_accounts: int = 200,
    linked_fraction: float = 0.6,
    max_txns_per_account: int = 12,
) -> Dataset:
    """Build the full linked dataset deterministically.

    ``linked_fraction`` of accounts get a telecom subscriber whose ``account_id`` points back, so the
    SIM-swap → bank-account bridge (Scenario B) is coherent. Returns a fresh, mutable ``Dataset``.
    """
    if Faker is None:  # pragma: no cover
        raise RuntimeError("faker is required: pip install -r demo-agents/requirements.txt")

    fake = Faker()
    Faker.seed(seed)
    rng = random.Random(seed)
    now = datetime(2026, 6, 1, tzinfo=timezone.utc)

    ds = Dataset()
    for i in range(n_accounts):
        account_id = f"acct-{1000 + i}"
        name = fake.name()
        account = {
            "account_id": account_id,
            "name": name,
            "email": fake.email(),
            "ssn_masked": _mask_ssn(rng),
            "balance": round(rng.uniform(50, 25_000), 2),
            "status": "active" if rng.random() > 0.05 else "frozen",
            "linked_msisdn": None,          # set below for the linked subset
            "opened_at": (now - timedelta(days=rng.randint(30, 2000))).isoformat(),
        }
        ds.accounts[account_id] = account

        # Transactions (PaySim-shaped).
        txns: List[dict] = []
        for t in range(rng.randint(3, max_txns_per_account)):
            amount = round(rng.uniform(5, 8_000), 2)
            is_fraud = 1 if (amount > 6_000 and rng.random() < 0.15) else 0
            txns.append(
                {
                    "txn_id": f"txn-{account_id[5:]}-{t:03d}",
                    "amount": amount,
                    "type": rng.choice(_TXN_TYPES),
                    "counterparty": fake.company(),
                    "txn_ts": (now - timedelta(days=rng.randint(0, 120), minutes=rng.randint(0, 1440))).isoformat(),
                    "fraud_label": is_fraud,
                }
            )
        txns.sort(key=lambda x: x["txn_ts"], reverse=True)
        ds.transactions[account_id] = txns

        # Linked telecom subscriber (IBM-Telco-style + Faker operational layer).
        if rng.random() < linked_fraction:
            msisdn = _msisdn(rng)
            account["linked_msisdn"] = msisdn
            ds.subscribers[msisdn] = {
                "msisdn": msisdn,
                "name": name,                        # same person as the bank account
                "plan": rng.choice(_PLANS),
                "sim_id": f"SIM{rng.randint(10**14, 10**15 - 1)}",
                "last_sim_change": (now - timedelta(days=rng.randint(60, 1500))).isoformat(),
                "account_id": account_id,            # bridge back to the bank account
                "tenure_months": rng.randint(1, 72),
                "monthly_charges": round(rng.uniform(20, 140), 2),
            }

    return ds


# A process-wide default snapshot, generated lazily, used by the in-memory store backend so tools
# return stable data without a database. Regenerate via reset_default_dataset() in tests.
_DEFAULT: Optional[Dataset] = None


def default_dataset() -> Dataset:
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = generate_dataset()
    return _DEFAULT


def reset_default_dataset() -> Dataset:
    global _DEFAULT
    _DEFAULT = generate_dataset()
    return _DEFAULT
