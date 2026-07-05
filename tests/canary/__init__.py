"""WS-J — synthetic canary + e2e test harness (Increment 1).

Transport-parameterized scenario library (tasks/serverless-edition/ws-j-canary-tests.md,
lld/38). ONE library, two runners: an in-process ``TestClient`` PR-gate (hermetic)
and a live-URL ECS hourly monitor. Every scenario is transport-agnostic — all
transport divergence lives in the ``canary_client`` fixture (conftest.py), never
in a scenario function (enforced by the transport-purity lint, Jc.2).

Increment 1 scope: J1 (harness + manifest), J2 (validate ALLOW/DENY/phase +
all-route positive/negative), J-cov (coverage guard + purity lint), J-report
(reporting plugin + three-state model + startup guard), J4 (redaction plumbing),
J6 (multi-tenant isolation). Deferred: J3/J5/J7/J8 (design in lld/38, no build).
"""
