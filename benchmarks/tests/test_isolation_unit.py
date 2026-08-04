"""Unit tests for the I1–I5 isolation chain (LLD 41 §4.7 / WS-B B1, B3).

The load-bearing one is :func:`test_i3_snapshots_before_mutation`: it is the
single test that would have caught the reversed draft in which I2 sentinelized
before I3 asserted, which makes I3 vacuous and the live-credential refusal test
unpassable.
"""
from __future__ import annotations

import os

import pytest

from benchmarks.core import isolation
from benchmarks.core.isolation import SENTINEL_CREDENTIAL, IsolationRecord

LIVE_LOOKING_KEY = "AKIAIOSFODNN7EXAMPLE"


class _FakeCredentials:
    """Stand-in for ``botocore.credentials.Credentials`` — only the two
    attributes I3 reads."""

    def __init__(self, access_key: str, method: str = "shared-credentials-file"):
        self.access_key = access_key
        self.secret_key = "secret"
        self.method = method


def _patch_credentials(monkeypatch, creds, observed=None):
    """Make botocore's provider chain resolve ``creds``.

    When ``observed`` is a list, the value of ``AWS_ACCESS_KEY_ID`` **at the
    moment the provider chain is consulted** is appended to it. That recording is
    what turns the ordering into something observable.
    """
    import botocore.session

    def _fake_get_credentials(_self):
        if observed is not None:
            observed.append(os.environ.get("AWS_ACCESS_KEY_ID"))
        return creds

    monkeypatch.setattr(
        botocore.session.Session, "get_credentials", _fake_get_credentials
    )


# --------------------------------------------------------------------------- #
# I3 — the ordering regression test
# --------------------------------------------------------------------------- #
def test_i3_snapshots_before_mutation(hermetic_env):
    """I3 must read the UNMUTATED environment, then refuse, and only I2 may write
    the sentinel — never the other way round.

    Two independent discriminators, both of which flip if the chain is
    "simplified" to sentinelize first:

    1. the value the provider chain saw was the developer's live key, not our
       sentinel (if I2 ran first it could only ever have seen the sentinel);
    2. the environment at the moment of the raise still holds the live key.
    """
    hermetic_env.setenv("AWS_ACCESS_KEY_ID", LIVE_LOOKING_KEY)
    hermetic_env.setenv("AWS_SECRET_ACCESS_KEY", "wJalrXUtnFEMI/EXAMPLEKEY")

    observed: list = []
    _patch_credentials(
        hermetic_env, _FakeCredentials(LIVE_LOOKING_KEY, method="env"), observed
    )

    with pytest.raises(SystemExit) as excinfo:
        isolation.enforce()

    assert excinfo.value.code == 2
    # 1 — the snapshot happened before any mutation.
    assert observed == [LIVE_LOOKING_KEY], (
        "I3 consulted the provider chain AFTER I2 wrote the sentinel — the "
        "assertion is vacuous in that order"
    )
    # 2 — and nothing was sentinelized on the way out.
    assert os.environ["AWS_ACCESS_KEY_ID"] == LIVE_LOOKING_KEY


def test_i3_accepts_already_sentinel(hermetic_env):
    """A shell already carrying the sentinel (a nested run) passes I3 rather than
    tripping it — otherwise the harness could not re-invoke its own entry
    points."""
    hermetic_env.setenv("AWS_ACCESS_KEY_ID", SENTINEL_CREDENTIAL)
    hermetic_env.setenv("AWS_SECRET_ACCESS_KEY", SENTINEL_CREDENTIAL)
    _patch_credentials(hermetic_env, _FakeCredentials(SENTINEL_CREDENTIAL, method="env"))

    record = isolation.enforce()
    try:
        assert isinstance(record, IsolationRecord)
        assert record.aws_credentials == "sentinel"
    finally:
        record.release()


def test_i3_refuses_when_the_chain_cannot_be_read(hermetic_env):
    """Fail secure: an unreadable provider chain means the negative cannot be
    asserted, so the run is refused rather than assumed safe."""
    import botocore.session

    def _boom(_self):
        raise OSError("credential chain unreadable")

    hermetic_env.setattr(botocore.session.Session, "get_credentials", _boom)

    with pytest.raises(SystemExit) as excinfo:
        isolation.enforce()
    assert excinfo.value.code == 2


# --------------------------------------------------------------------------- #
# I2 — the credential floor
# --------------------------------------------------------------------------- #
def test_i2_sets_sentinel_and_pops_profile(hermetic_env):
    """After a clean ``enforce()`` both key vars are the sentinel and the profile
    chain is gone — I2 must overwrite *and* pop, because a surviving
    ``AWS_PROFILE`` re-arms the shared-credentials provider."""
    hermetic_env.setenv("AWS_PROFILE", "sentra")
    hermetic_env.setenv("AWS_SESSION_TOKEN", "FwoGZXIvYXdzEXAMPLE")
    _patch_credentials(hermetic_env, None)

    record = isolation.enforce()
    try:
        assert os.environ["AWS_ACCESS_KEY_ID"] == SENTINEL_CREDENTIAL
        assert os.environ["AWS_SECRET_ACCESS_KEY"] == SENTINEL_CREDENTIAL
        assert "AWS_PROFILE" not in os.environ
        assert "AWS_SESSION_TOKEN" not in os.environ
        assert record.aws_credentials == "sentinel"
    finally:
        record.release()


# --------------------------------------------------------------------------- #
# I1 — the badge
# --------------------------------------------------------------------------- #
def test_i1_missing_badge_raises_systemexit_2(hermetic_env):
    """Unbadged is a refusal, and the exit *code* is exactly 2 — not 1, which is
    what ``raise SystemExit("message")`` would have produced."""
    hermetic_env.delenv("AEGION_BENCHMARK", raising=False)

    with pytest.raises(SystemExit) as excinfo:
        isolation.enforce()
    assert excinfo.value.code == 2


def test_i1_wrong_badge_value_raises(hermetic_env):
    """``AEGION_BENCHMARK=true`` is not ``1``. The badge is an exact match so it
    cannot be satisfied by accident."""
    hermetic_env.setenv("AEGION_BENCHMARK", "true")

    with pytest.raises(SystemExit) as excinfo:
        isolation.enforce()
    assert excinfo.value.code == 2


def test_i1_fires_before_i3(hermetic_env):
    """The badge is checked first: an unbadged shell is refused without the
    provider chain ever being consulted."""
    hermetic_env.delenv("AEGION_BENCHMARK", raising=False)
    observed: list = []
    _patch_credentials(hermetic_env, None, observed)

    with pytest.raises(SystemExit):
        isolation.enforce()
    assert observed == []


# --------------------------------------------------------------------------- #
# I5 — the prod-target denylist
# --------------------------------------------------------------------------- #
def test_i5_rejects_prod_host(hermetic_env):
    """A hosted run aimed at a ``PROD_HOSTS`` entry is refused; a non-prod host
    passes. 'Point it at prod just this once' must not be one CLI flag away."""
    _patch_credentials(hermetic_env, None)
    hermetic_env.setattr(isolation, "_resolve_account_id", lambda: None)

    prod_url = "https://iw3limi4k7.execute-api.us-east-1.amazonaws.com/prod"
    with pytest.raises(SystemExit) as excinfo:
        isolation.enforce(transport="hosted", base_url=prod_url)
    assert excinfo.value.code == 2

    record = isolation.enforce(
        transport="hosted", base_url="https://benchmark-engine.internal.test/v1"
    )
    try:
        assert record.prod_target_check == "passed"
    finally:
        record.release()


@pytest.mark.parametrize(
    "prod_url",
    [
        "https://iw3limi4k7.execute-api.us-east-1.amazonaws.com/prod",
        "https://sentra-public-alb-1320390749.us-east-1.elb.amazonaws.com/v1",
        # A re-created ALB keeps the name and changes only the numeric suffix —
        # the fragment rule has to catch that, or the denylist rots on the first
        # redeploy.
        "https://sentra-public-alb-999999999.us-east-1.elb.amazonaws.com/v1",
        "http://internal-sentra-private-alb-760501353.us-east-1.elb.amazonaws.com",
        "sentra-api-nlb-f00bf616b8803daf.elb.us-east-1.amazonaws.com:443",
    ],
)
def test_i5_rejects_every_known_prod_host(hermetic_env, prod_url):
    _patch_credentials(hermetic_env, None)
    hermetic_env.setattr(isolation, "_resolve_account_id", lambda: None)

    with pytest.raises(SystemExit) as excinfo:
        isolation.enforce(transport="hosted", base_url=prod_url)
    assert excinfo.value.code == 2


def test_i5_rejects_prod_account(hermetic_env):
    """Even a benign-looking hostname is refused if the credentials resolve to
    the production account."""
    _patch_credentials(hermetic_env, None)
    hermetic_env.setattr(
        isolation, "_resolve_account_id", lambda: isolation.PROD_ACCOUNT_ID
    )

    with pytest.raises(SystemExit) as excinfo:
        isolation.enforce(
            transport="hosted", base_url="https://benchmark-engine.internal.test/v1"
        )
    assert excinfo.value.code == 2


def test_i5_not_applied_in_process(hermetic_env):
    """An in-process run reaches no endpoint, so it must not attempt an STS call
    at all — a network round trip the default transport has no business making."""
    _patch_credentials(hermetic_env, None)

    def _must_not_be_called():
        raise AssertionError("in-process run attempted an STS account lookup")

    hermetic_env.setattr(isolation, "_resolve_account_id", _must_not_be_called)

    record = isolation.enforce()
    try:
        assert record.prod_target_check == "skipped"
    finally:
        record.release()


def test_i5_reads_base_url_from_argv_when_not_passed(hermetic_env):
    """``enforce()`` has to apply I5 while still being literally the first
    executable statement of an entry point — i.e. before argparse has run — so it
    falls back to scanning ``sys.argv``."""
    _patch_credentials(hermetic_env, None)
    hermetic_env.setattr(isolation, "_resolve_account_id", lambda: None)
    hermetic_env.setattr(
        "sys.argv",
        [
            "run.py",
            "--transport",
            "hosted",
            "--base-url=https://iw3limi4k7.execute-api.us-east-1.amazonaws.com/prod",
        ],
    )

    with pytest.raises(SystemExit) as excinfo:
        isolation.enforce()
    assert excinfo.value.code == 2


# --------------------------------------------------------------------------- #
# B5 — the manifest block (a data carrier; shape only)
# --------------------------------------------------------------------------- #
def test_isolation_record_serializes_all_six_fields(hermetic_env):
    """``manifest.isolation`` carries all six fields, never the contextvar token,
    and never an actual credential value (SEC-2)."""
    _patch_credentials(hermetic_env, None)

    record = isolation.enforce()
    try:
        block = record.to_dict()
        assert set(block) == {
            "tenant",
            "badge",
            "aws_credentials",
            "metrics_publisher",
            "audit_writer",
            "prod_target_check",
        }
        assert block == {
            "tenant": "_benchmark",
            "badge": True,
            "aws_credentials": "sentinel",
            "metrics_publisher": "NullMetricsPublisher",
            "audit_writer": "NullAuditWriter",
            "prod_target_check": "skipped",
        }
        # The state, never the key — not even the sentinel's value.
        assert SENTINEL_CREDENTIAL not in str(block)
    finally:
        record.release()
