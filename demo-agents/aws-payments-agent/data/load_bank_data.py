#!/usr/bin/env python3
"""Load the bank dataset (accounts + transactions) into DynamoDB (LLD 22 §8.1/§8.3).

PaySim-shaped transactions + Faker PII, generated deterministically by ``common/datagen.py``. Creates
the on-demand tables if absent, then bulk-writes. Idempotent (puts overwrite by key).

    python aws-payments-agent/data/load_bank_data.py            # create + load
    python aws-payments-agent/data/load_bank_data.py --dry-run  # preview counts only
    python aws-payments-agent/data/load_bank_data.py --n-accounts 500
"""
from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))  # demo-agents/
from common import datagen, ddb_admin  # noqa: E402
from common.store import DEFAULT_ACCOUNTS_TABLE, DEFAULT_TXNS_TABLE  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Load acme-bank-accounts / -transactions")
    ap.add_argument("--n-accounts", type=int, default=200)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    ds = datagen.generate_dataset(n_accounts=args.n_accounts)
    accounts = list(ds.accounts.values())
    # Stamp account_id (the table's partition key) onto each txn, and dedup by (account_id, txn_ts)
    # so a batch_writer never silently overwrites two txns sharing a synthesized timestamp.
    seen = set()
    txns = []
    for account_id, lst in ds.transactions.items():
        for t in lst:
            key = (account_id, t["txn_ts"])
            if key in seen:
                continue
            seen.add(key)
            txns.append(dict(t, account_id=account_id))
    print(f"Generated {len(accounts)} accounts, {len(txns)} transactions, "
          f"{len(ds.subscribers)} linked subscribers.")

    if args.dry_run:
        print("DRY RUN — nothing written. Sample account:")
        print(" ", accounts[0])
        return 0

    ddb = ddb_admin._resource()
    ddb_admin.ensure_table(
        ddb, DEFAULT_ACCOUNTS_TABLE,
        key_schema=[{"AttributeName": "account_id", "KeyType": "HASH"}],
        attr_defs=[{"AttributeName": "account_id", "AttributeType": "S"}],
    )
    ddb_admin.ensure_table(
        ddb, DEFAULT_TXNS_TABLE,
        key_schema=[{"AttributeName": "account_id", "KeyType": "HASH"},
                    {"AttributeName": "txn_ts", "KeyType": "RANGE"}],
        attr_defs=[{"AttributeName": "account_id", "AttributeType": "S"},
                   {"AttributeName": "txn_ts", "AttributeType": "S"}],
    )
    ddb_admin.bulk_put(ddb, DEFAULT_ACCOUNTS_TABLE, accounts)
    ddb_admin.bulk_put(ddb, DEFAULT_TXNS_TABLE, txns)
    print("✅ bank data loaded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
