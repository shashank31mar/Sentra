# Integrating AegionAI Guard with Cursor

**In one line:** Cursor lets a script run at each step of its AI agent's loop and *wait* for a yes/no before the agent acts. We ship that script. It calls our policy engine and blocks the dangerous action before it happens.

We do **not** modify Cursor and Cursor does **not** build anything for us — Cursor already shipped the doorway (called **Agent Hooks**). We plug into it.

---

## How it works

Cursor's agent doesn't run a command or edit a file directly — just before it does, it calls out to any script you've registered for that step, hands it the details as JSON, and waits for a reply. A reply of `deny` stops the action. That waiting-and-obeying is Cursor's designed behavior, not something we bolt on.

Our script is a small "checkpoint" (the same enforcement pattern we already run for AWS Bedrock and Azure). It takes the action Cursor is about to perform, asks our policy engine `POST /v1/validate`, and returns Cursor's answer.

```mermaid
sequenceDiagram
    participant Agent as Cursor AI agent
    participant Cursor as Cursor app
    participant Hook as Our hook script (checkpoint)
    participant PDP as AegionAI policy engine

    Agent->>Cursor: "Run: aws s3 rb s3://prod-backups --force"
    Cursor->>Hook: beforeShellExecution { command, cwd } — and waits
    Hook->>PDP: POST /v1/validate (the action + who + context)
    PDP-->>Hook: block — "destructive op on a production resource"
    Hook-->>Cursor: { "permission": "deny", reason }
    Cursor--xAgent: command NOT run; shows the reason
```

## A concrete example

A developer tells Cursor's agent: *"clean up old files and redeploy."* Mid-task, the agent decides to run:

```
aws s3 rb s3://prod-backups --force      # delete a production backup bucket
```

1. **Before** running it, Cursor spawns our hook and passes `{ "command": "aws s3 rb s3://prod-backups --force", "cwd": "..." }`.
2. Our hook calls `POST /v1/validate`. The engine sees a destructive action on a production resource and returns **block**.
3. Our hook replies to Cursor: `{ "permission": "deny", "user_message": "Blocked: deletes a production bucket", "agent_message": "This action was blocked by policy." }`.
4. Cursor **does not run the command**, shows the developer why, and tells the agent so it doesn't blindly retry.

The same works for the agent calling an external tool (`beforeMCPExecution`), writing a file — e.g. pasting a secret into source (`preToolUse` with a `Write` match) — or reading a sensitive file (`beforeReadFile`).

To turn it on, one small config file (`hooks.json`) points Cursor at our script:

```json
{ "version": 1,
  "hooks": {
    "beforeShellExecution": [{ "command": "./aegion-guard-hook", "failClosed": true }],
    "beforeMCPExecution":  [{ "command": "./aegion-guard-hook", "failClosed": true }],
    "preToolUse":          [{ "command": "./aegion-guard-hook", "matcher": "Write", "failClosed": true }]
  } }
```

`failClosed: true` matters: Cursor's default is to *allow* an action if the check errors out. We flip it so a failed or slow check **blocks** — deny-by-default, our core rule.

---

## What we do vs. what Cursor already does

| We build & operate | Cursor provides (already shipped) | The customer's IT admin does |
|---|---|---|
| The hook script (the checkpoint) | The Agent Hooks doorway — spawns our script at each `before…` step and **waits** | Installs the script + `hooks.json` across the team |
| Calls `POST /v1/validate` and maps the verdict to `allow` / `deny` | Honors `deny` — actually stops the action, shows the reason | Pushes it centrally (MDM / Team dashboard) so it applies fleet-wide |
| The policy engine that decides | Passes us the action details + who + session id as JSON | Uses managed devices + SSO so it can't be casually turned off |
| Sets `failClosed: true`, logs every decision | — | — |
| A conformance test that re-proves, each Cursor release, that hooks fire and `deny` truly blocks | — | — |

**No "special validation hook" is needed** — the `before…` events *are* the validation point. Returning `deny` is the documented way to block; we additionally verify (via the paired `after…` events) that the blocked action genuinely never ran.

## Two honest limits

- **Latency.** Every checked action waits on our engine. On our cloud offering that's ~0.6–1.2s per call, and an agent can fire dozens per task — too slow for interactive coding. The **in-VPC edition** (the check runs next to the developer, on-box) is what makes it fast enough. Cursor is the use case that makes in-VPC a requirement, not a nice-to-have.
- **Not "unbreakable" on an unmanaged laptop.** Cursor lets an admin push this fleet-wide, and a company-managed policy wins over a developer's own setting. But a developer with admin rights on their own machine could remove it. Honest claim: **enforced across a managed fleet** (central push + managed devices + SSO) — we reserve "non-bypassable" for our network sidecar, which sits physically in the path.
