# WS-J canary suite (`tests/canary/`) — Increment 1

Transport-parameterized synthetic canary + e2e harness. ONE scenario library, two
runners (lld/38, `tasks/serverless-edition/ws-j-canary-tests.md`):

- **PR-gate (Runner A)** — in-process `TestClient`, hermetic (moto, no AWS, no PII):
  ```
  env -u AWS_PROFILE AWS_ACCESS_KEY_ID=testing AWS_SECRET_ACCESS_KEY=testing \
      AWS_DEFAULT_REGION=us-east-1 PYTHONPATH=src/security-controller \
      src/security-controller/venv/bin/python -m pytest tests/canary/ -v \
      -p no:cacheprovider -m "not requires_live and not pr_gate_only"
  ```
- **ECS hourly monitor (Runner B)** — the `sentra/canary` image runs it against the
  live API Gateway with `CANARY_TARGET=live` + the reporting plugin (writes
  `sentra-canary-results`, emits `Sentra/Canary` metrics, SNS→`shshgup@amazon.com`).

## P0-2 coverage gate (Jc.3 — `inprocess` only, `--cov-fail-under=85`)

`85%` is a **target-to-tune label**, not a proven floor. The gate is `inprocess`-only
(the black-box `live` monitor cannot instrument the remote process):

```
env -u AWS_PROFILE AWS_ACCESS_KEY_ID=testing AWS_SECRET_ACCESS_KEY=testing \
    AWS_DEFAULT_REGION=us-east-1 PYTHONPATH=src/security-controller \
    src/security-controller/venv/bin/python -m pytest tests/canary/ \
    -m "not requires_live and not pr_gate_only" \
    --cov=app/api --cov=app/services --cov-fail-under=85 --cov-report=term-missing
```

## Markers

- `requires_live` — needs a live deployed target (`SENTRA_API_GW_URL`); skipped in the
  PR-gate. Also covers routes that cannot be exercised hermetically (e.g. metrics
  reading CloudWatch `GetMetricData`, which moto does not emulate).
- `pr_gate_only` — runs only in the in-process PR-gate, never the hourly prod monitor
  (billing-hygiene J5 will use this when WS-H lands).

## Increment-1 scope (built)

J1 (harness + `route_manifest`), J2 (validate ALLOW/DENY/phase + all-route
positive/negative), J-cov (coverage guard + transport-purity lint + cov gate),
J-infra (`cdk/stacks/canary_stack.py` + `docker/canary/Dockerfile` + ECR/DDB/scheduler/
SNS), J-report (reporting plugin + three-state model + at-most-one guard), J4
(redaction plumbing), J6 (multi-tenant isolation).

Deferred (design in lld/38, no build): J3 (differential conformance — WS-A/WS-I),
J5 (metering — WS-H), J7 (authz 403 gate — WS-M), J8 (console UI + Playwright + the
16 OIDC routes — Increment 2).
