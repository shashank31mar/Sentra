# AegionAI Guard — Integration Docs

Everything a customer needs to integrate their AI agents with AegionAI Guard.

| File | What it is | Audience |
|---|---|---|
| [`aegion-guard-api.openapi.yaml`](aegion-guard-api.openapi.yaml) | **Full** API reference (every endpoint), tagged by audience | Internal teams |
| `aegion-guard-api.customer.openapi.yaml` | **Customer-safe subset** (internal ops stripped) — *generated* | Share with customers |
| [`build_customer_openapi.py`](build_customer_openapi.py) | Generates the customer subset from the full spec | — |
| [`sdk-integration-guide.md`](./sdk-integration-guide.md) | **SDK** how-to (annotations, examples) | Customer engineers |
| [`redocly.yaml`](redocly.yaml) | Lint ruleset | — |

The **SDK guide is the recommended path**; the **OpenAPI spec is the fallback** for non-Python agents or direct HTTP integration.

---

## One spec, two audiences

The full `openapi.yaml` is the single source of truth. Every operation carries:

- `tags:` — functional grouping (Integration, Read & Reporting, Policies, …)
- `x-audience:` — `customer-integration` · `customer-reporting` · `customer-admin` · `internal`
- `x-internal: true` — on operations **not** meant for customers (SOC-console discovery, FP/FN verdict tagging, raw signal stream).

`x-internal: true` is honored two ways:
1. **ReDoc/Redocly hide it automatically** when rendering — so the same file renders as the full internal reference *or* a customer doc.
2. **`build_customer_openapi.py`** strips those operations (and orphaned tags/schemas) into a standalone file you can hand over.

```bash
# Customer-safe subset (drops x-internal)
python build_customer_openapi.py
#   -> aegion-guard-api.customer.openapi.yaml   (36 paths, 43 operations)

# Tighter: only the agent-integration surface (validate + health + edge-signal)
python build_customer_openapi.py --audience customer-integration --out integration-only.openapi.yaml
```

---

## Render it (Swagger/ReDoc)

```bash
# Live preview (ReDoc) — hides x-internal automatically
npx @redocly/cli preview-docs aegion-guard-api.openapi.yaml

# A single shareable HTML file for a customer
npx @redocly/cli build-docs aegion-guard-api.customer.openapi.yaml -o aegion-guard-api.html

# Swagger UI: paste the YAML into https://editor.swagger.io
# Lint: 
npx @redocly/cli lint aegion-guard-api.openapi.yaml --config redocly.yaml
```

---

## The 60-second integration

Authenticate every request with the per-tenant key in the **`x-api-key`** header, then call
`POST /v1/validate` **before** each tool runs:

```bash
curl -s https://<host>/prod/v1/validate \
  -H "x-api-key: $AEGION_API_KEY" -H "Content-Type: application/json" \
  -d '{
    "request_id": "req-abc123",
    "session_id": "sess-7f3a91",
    "agent_id": "acme-payments-agent",
    "tool_name": "process_refund",
    "tool_params": { "account_id": "acct-1007", "amount": 120.0 },
    "user_input": "please refund my $120 order",
    "timestamp": "2026-06-10T10:00:00.000Z",
    "operation_type": "WRITE"
  }'
```

- `decision: ALLOW` → run the tool.
- `decision: DENY` → **do not** run it; surface `reason`.
- Reuse `session_id` across a conversation (so trust decay, quarantine, and cross-cloud
  preconditions work); thread `request_id` for tracing.

Prefer not to hand-roll HTTP? Use the [SDK](./sdk-integration-guide.md) — one decorator per tool.
