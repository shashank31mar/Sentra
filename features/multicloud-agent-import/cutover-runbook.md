# Tenancy v2 Cutover Runbook (P0a / workstream M0c–M0d, T09)

Operational procedure for flipping `TENANCY_V2_ENABLED` from the v1 (flat) tables
to the v2 (tenant-scoped) tables **without** a fleet-wide DENY. Read alongside
[workstream.md](./workstream.md) §1.2 (flag), §5 (T09/T10) and [feature.md](./feature.md) §14.2.

> **The single most dangerous fact:** the validate hot path resolves an agent's
> policy through `policies-metadata.agent-index`. Reads and writes must flip
> **together** (one flag) and the rollout must never serve a half-migrated mix —
> a stale-flag task querying the new GSI by bare `agent_id` resolves no policy →
> `POLICY_NOT_FOUND` → DENY. The write-freeze below is what prevents that.

## 0. Preconditions (all must be green)

- [ ] M0a deployed: the four `*-v2` tables exist (`cdk diff` showed only the new
      tables). Controller task role already has read/write on them (T02 grants).
- [ ] `TENANCY_V2_ENABLED=false` everywhere (default). Confirm in the running
      task's env.
- [ ] Controller `pytest` green, including `tests/test_tenancy_v2.py` (flag-on path).
- [ ] AWS creds fresh: `aws sts get-caller-identity --profile sentra`
      (refresh with `ada cred update --once --profile sentra` if expired).

## 1. Pre-migration bulk copy (no freeze, no flag change)

Idempotent; safe to run repeatedly. The controller keeps serving from v1.

```bash
python scripts/migrate_tenancy.py --dry-run     # review per-table counts + added attrs
python scripts/migrate_tenancy.py               # bulk copy v1 -> v2 under tenant=default
python scripts/migrate_tenancy.py               # re-run: must be a no-op (idempotent)
```

## 2. Write-freeze cutover (low-traffic window)

MVP traffic is low, so a brief write-freeze is simpler and safer than dual-write
(feature §14.2). Steps, in order:

1. **Freeze writes.** Put the controller into read-only / brief maintenance so no
   new agents, policies, sessions, or signals are written.
2. **Final delta copy.** `python scripts/migrate_tenancy.py` once more — re-copies
   anything written since step 1. (Deletes are NOT propagated; the freeze is what
   keeps that window closed.)
3. **Parity snapshot — take it INSIDE the freeze** (T10b): every agent that
   resolved an active policy on v1 must still resolve on v2. A write landing
   between the delta copy and the flag flip would false-fail this, hence the freeze.
4. **Flip the flag.** Set `TENANCY_V2_ENABLED=true` in the controller task env and
   `--force-new-deployment`.
5. **WAIT for the new deployment to fully stabilize** — all old-flag tasks drained.
   `min/max-healthy = 50/200` runs old+new concurrently mid-rollout; unfreezing
   before the old tasks drain splits writes across v1/v2.
6. **Unfreeze.**

## 3. Verify (T10 — sign-off gate)

- [ ] **Isolation through real endpoints** (not just GSI gets): seed a
      `tenant=other` row in each table; a default-tenant caller hitting
      `GET /v1/agents`, the discovery/import list, session-count/trust reads,
      `GET /v1/policies`, and `GET /v1/decisions` sees **zero** `other` rows.
- [ ] **Fail-secure parity**: live `/v1/validate` for a known agent ALLOWs via the
      v2 policy; no new `POLICY_NOT_FOUND`.
- [ ] **GET /v1/decisions non-empty** (decision-date GSI regression guard).
- [ ] **Signal `sk` / `decision_date` byte-match** the v1 source rows.

`tests/test_tenancy_v2.py` automates the isolation + GSI + byte-match checks
against moto; the live checks above confirm the same against the deployed stack.

## 4. Rollback

Rollback is the **same concurrent-rollout mechanism** and is therefore also
freeze-gated: set `TENANCY_V2_ENABLED=false`, `--force-new-deployment`, and keep
the write-freeze until the rollout stabilizes — never a live unfrozen flip. The
v1 tables are `RETAIN`ed and untouched, so they are still authoritative.

## 5. After sign-off (separate change, not this milestone)

- Re-point seed scripts' default env (`TENANCY_V2_ENABLED=true`) so re-seeding
  never re-creates flat v1 rows (T08 already makes them flag-aware).
- Deleting the v1 tables requires its own founder sign-off (out of scope here).
