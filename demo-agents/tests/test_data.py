"""Data layer tests: deterministic generation, account↔subscriber linkage, store ops."""
from __future__ import annotations

import pytest

from common import datagen, store


def test_dataset_deterministic_and_linked():
    ds = datagen.reset_default_dataset()
    assert len(ds.accounts) == 200
    assert ds.subscribers, "expected some linked subscribers"
    for msisdn, sub in ds.subscribers.items():
        acct = ds.accounts[sub["account_id"]]
        assert acct["linked_msisdn"] == msisdn  # bidirectional link integrity


def test_dataset_is_reproducible():
    a = datagen.generate_dataset(seed=7, n_accounts=20)
    b = datagen.generate_dataset(seed=7, n_accounts=20)
    assert list(a.accounts) == list(b.accounts)
    assert a.accounts["acct-1000"]["balance"] == b.accounts["acct-1000"]["balance"]


def test_store_memory_refund_and_fraud():
    datagen.reset_default_dataset()
    acct = "acct-1000"
    before = store.get_account(acct)["balance"]
    r = store.process_refund(acct, 100.0)
    assert r["success"] and r["new_balance"] == round(before + 100.0, 2)
    assert store.fraud_score("acct-1000")["risk"] in ("high", "med", "low")
    assert store.check_fraud_score("txn-1")["fraud_score"] == store.fraud_score("txn-1")["fraud_score"]


def test_store_not_found():
    datagen.reset_default_dataset()
    with pytest.raises(store.NotFound):
        store.get_account("acct-nope")
