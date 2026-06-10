# demo-agents — Cross-Cloud Demo Agents (WS-23 Track 2)

Three business-realistic agents that integrate with the AegionAI security controller through the
[`aegion-guard`](sdk/aegion-guard-python/) SDK, driven by real-shaped open-source data, so ALLOW/DENY
decisions flow into `console.aegionai.ai`.

| Agent | Cloud | Tools |
|---|---|---|
| `acme-payments-agent` | AWS Bedrock (Nova Lite, no guardrail) | `lookup_account`, `get_transactions`, `process_refund`, `transfer_funds` |
| `acme-identity-agent` | Azure OpenAI (gpt-4o-mini) | `verify_identity`, `check_fraud_score` |
| `acme-telecom-agent` | Azure OpenAI (gpt-4o-mini) | `lookup_subscriber`, `change_plan`, `reset_sim`, `port_out_number` |

**Cross-cloud scenarios** (enforced by the core `context_validator`, no core change):
- **A (finance + identity):** a refund/transfer is DENIED unless `verify_identity` ran for the same session within 300s.
- **B1 (finance + telecom):** an unauthenticated `reset_sim` / `port_out_number` (SIM-swap) is DENIED unless `verify_identity` ran first.

See [LLD 22](../lld/22-cross-cloud-demo-agents.md) and [WS-23](../tasks/workstream-23-cross-cloud-demo-agents.md).

## Layout
```
demo-agents/
├── sdk/aegion-guard-python/     # the published SDK (WS-23 M1) — agents depend on it
├── common/                      # shared data generator + runtime store
├── aws-payments-agent/          # Bedrock agent: tools, spec, data loader, deploy
├── azure-identity-agent/        # Azure Function agent: tools, spec, data, infra
├── azure-telecom-agent/         # Azure Function agent: tools, spec, data, infra
├── registration/                # agents.demo.yaml + policies.demo.yaml + seed_demo.py
├── traffic/                     # continuous traffic generator + schedule
└── tests/                       # offline unit + gated integration tests
```

## Data realism (LLD 22 §8.3)
`common/datagen.py` produces a **deterministic, linked** synthetic dataset (Faker) shaped like the
public datasets — **PaySim** (transactions), **IEEE-CIS** (fraud features), **IBM Telco Churn**
(subscribers). Drop real CSVs in `data/raw/` to enrich; otherwise the Faker generator is fully
runnable offline. **Only synthetic/derived rows are committed — never raw dataset PII.**

## Core-enforcement reality (LLD 22 §6.5 — read before editing policies)
The policy engine is **tool-name-hardcoded**, it does NOT evaluate rule strings:
- Refund DENY = the **hardcoded $5000 default** (not configurable via the policy API).
- `transfer_funds` has **no** amount limit in core — its guard is the cross-cloud verify precondition.
- Real DENYs come from **sigma/injection**, **refund>$5000**, and **cross-cloud preconditions**. Do not encode rule-string amount limits.

## Quick start (offline)
```bash
pip install -e sdk/aegion-guard-python -r requirements.txt
pytest tests/ -q                     # offline unit tests (in-memory store, mocked validate)
```

## Deploy (needs live cloud creds — see each agent's deploy/ + infra/)
```bash
export SENTRA_API_BASE=https://<id>.execute-api.us-east-1.amazonaws.com/prod
export SENTRA_API_KEY=<usage-plan key>     # server-side only
# AWS:   ada cred update --profile sentra; python aws-payments-agent/deploy/deploy_payments_agent.py --create
# Azure: cd azure-identity-agent && azd up   (and azure-telecom-agent)
# then:  python registration/seed_demo.py
```
