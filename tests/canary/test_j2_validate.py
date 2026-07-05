"""WS-J J2 — validate ALLOW/DENY round-trip + per-phase (P0-1 headline).

Drives the real ``POST /v1/validate`` → ``DenyOverrides`` combiner → response seam
end-to-end over the ``canary_client`` transport (Invariant 3). A DENY is a
successful validation (HTTP 200 + ``decision=="DENY"``) — asserting DENY via a
4xx/5xx is the forbidden fail-open form (Invariant 4 / J2.2 footgun).
"""
from __future__ import annotations

import pytest

from app.api.models import KNOWN_PHASES
from canary import scenarios


def test_j2_1_allow(canary_client):
    scenarios.scenario_j2_1_allow(canary_client)


def test_j2_2_deny(canary_client):
    scenarios.scenario_j2_2_deny(canary_client)


@pytest.mark.parametrize("phase", sorted(KNOWN_PHASES))
def test_j2_3_phases(canary_client, phase):
    scenarios.scenario_j2_3_phase(canary_client, phase)


def test_j2_3_unknown_phase_422(canary_client):
    scenarios.scenario_j2_3_unknown_phase(canary_client)
