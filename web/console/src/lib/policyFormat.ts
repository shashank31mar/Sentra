import type { PolicyDetailView } from '../types/api'

/**
 * Render a Sentra agent policy's content for the source viewer (CEDAR / YAML / JSON) and a couple
 * of small helpers. Sentra policies are agent YAML configs (allowed_tools, cross_cloud_dependencies,
 * inner rules, rate limit); the YAML/JSON tabs show the real authored content, while the CEDAR tab
 * renders an equivalent Cedar policy (passing raw content through when it is already Cedar, else
 * projecting the structured fields). All parsing is best-effort and null-safe: live content can be
 * an object, a string, or null.
 */
export type PolicyLang = 'cedar' | 'yaml' | 'json'

/** Coerce content to a string (the live API may return an object, a YAML string, or null). */
export function contentToString(content: unknown): string {
  if (content === null || content === undefined) return ''
  if (typeof content === 'string') return content
  try {
    return JSON.stringify(content, null, 2)
  } catch {
    return String(content)
  }
}

function scalar(v: unknown): string {
  if (v === null || v === undefined) return 'null'
  if (typeof v === 'number' || typeof v === 'boolean') return String(v)
  const s = String(v)
  // Quote when YAML would otherwise mis-parse (special chars, leading/trailing space, empty).
  return s === '' || /[:#\-?{}[\],&*!|>'"%@`]/.test(s) || s.trim() !== s ? JSON.stringify(s) : s
}

/** Minimal, dependency-free object → YAML. Handles nested objects, arrays, and scalars. */
export function toYaml(value: unknown, indent = 0): string {
  const pad = '  '.repeat(indent)

  if (Array.isArray(value)) {
    if (value.length === 0) return `${pad}[]`
    return value
      .map((item) => {
        if (item && typeof item === 'object') {
          const block = toYaml(item, indent + 1).replace(new RegExp(`^${'  '.repeat(indent + 1)}`), '')
          return `${pad}- ${block.trimStart()}`
        }
        return `${pad}- ${scalar(item)}`
      })
      .join('\n')
  }

  if (value && typeof value === 'object') {
    const entries = Object.entries(value as Record<string, unknown>)
    if (entries.length === 0) return `${pad}{}`
    return entries
      .map(([k, v]) => {
        if (Array.isArray(v)) {
          return v.length === 0 ? `${pad}${k}: []` : `${pad}${k}:\n${toYaml(v, indent + 1)}`
        }
        if (v && typeof v === 'object') {
          return `${pad}${k}:\n${toYaml(v, indent + 1)}`
        }
        return `${pad}${k}: ${scalar(v)}`
      })
      .join('\n')
  }

  return `${pad}${scalar(value)}`
}

/** Render the policy content in the requested language for the code viewer. */
export function renderContent(content: unknown, lang: PolicyLang): string {
  if (content === null || content === undefined) return '# No policy content available'
  // If the API handed back a YAML string, show it as-is in YAML mode.
  if (lang === 'yaml') return typeof content === 'string' ? content : toYaml(content)
  return typeof content === 'string' ? content : JSON.stringify(content, null, 2)
}

const cedarId = (v: string) => `"${String(v).replace(/"/g, '\\"')}"`

/**
 * Render the policy as a Cedar policy for the CEDAR source tab. If the raw content is already a
 * Cedar string (contains a `permit`/`forbid` head) it is shown verbatim; otherwise an equivalent
 * Cedar policy is projected from the normalized Sentra fields: the agent is the `principal`,
 * `allowed_tools` become the permitted `action in [...]`, and the rate limit + cross-cloud
 * preconditions become `when {}` conditions. Each inner DENY rule is emitted as a `forbid` block.
 */
/**
 * The per-agent authorization VALUES (the Cedar entity store) shown as a comment
 * block. In the Cedar model the authorization RULES are universal (identical for
 * every agent); all per-agent variance — allow-lists, refund cap, callable agents
 * — lives in the entity store, NOT the rule text. So the generic baseline alone
 * looks "not up to date" per policy; this block surfaces THIS agent's actual
 * values so the CEDAR view reflects the specific policy (review feedback Q1).
 */
function entityValuesComment(policy: PolicyDetailView): string {
  const lines = [
    `// ── Authorization for ${policy.agent_id ?? policy.policy_id}`
    + `${policy.version ? ` · v${policy.version}` : ''} (this agent's Cedar entity attributes) ──`,
    `// allowed_tools  = [${policy.allowed_tools.join(', ') || '—'}]`,
    `// allowed_agents = [${policy.allowed_agents.join(', ') || '—'}]`,
  ]
  if (policy.max_refund_amount != null) {
    lines.push(`// max_refund_amount = $${policy.max_refund_amount.toLocaleString()}`
      + ` (${policy.max_refund_amount * 100} cents)`)
  }
  if (policy.max_calls_per_minute != null) {
    lines.push(`// max_calls_per_minute = ${policy.max_calls_per_minute}  (enforced by abuse_detector, not Cedar)`)
  }
  return lines.join('\n')
}

export function renderCedar(policy: PolicyDetailView): string {
  // cedar-policy CT13/CT13a: when the backend has compiled Cedar, the RULES it
  // evaluates are the universal baseline — so we prepend THIS agent's entity
  // values so the view is per-policy and matches what's actually enforced.
  if (policy.cedar_content && policy.cedar_content.trim()) {
    return `${entityValuesComment(policy)}\n\n${policy.cedar_content.trim()}`
  }

  const raw = policy.content
  if (typeof raw === 'string' && /\b(permit|forbid)\s*\(/i.test(raw)) return raw.trim()

  const principal = policy.agent_id ? `Agent::${cedarId(policy.agent_id)}` : 'principal'
  const lines: string[] = [
    `// Cedar projection of Sentra agent policy ${policy.policy_id}${policy.version ? ` · v${policy.version}` : ''}`,
    '// Derived from allowed_tools, rate limit, cross-cloud preconditions & inner rules.',
    '',
  ]

  const actions = policy.allowed_tools.length
    ? `action in [${policy.allowed_tools.map((t) => `Action::${cedarId(t)}`).join(', ')}]`
    : 'action'

  const conditions: string[] = []
  if (policy.max_calls_per_minute != null) {
    conditions.push(`context.calls_per_minute <= ${policy.max_calls_per_minute}`)
  }
  for (const d of policy.cross_cloud_dependencies) {
    if (!d.target_agent || !d.target_tool) continue
    const within =
      typeof d.max_age_seconds === 'number' ? ` && context.age_seconds <= ${d.max_age_seconds}` : ''
    conditions.push(`context.called(${cedarId(`${d.target_agent}.${d.target_tool}`)})${within}`)
  }

  lines.push('permit (', `    principal == ${principal},`, `    ${actions},`, '    resource', ')')
  if (conditions.length) {
    lines.push('when {', conditions.map((c) => `    ${c}`).join(' &&\n'), '};')
  } else {
    lines[lines.length - 1] = ');'
  }

  for (const r of policy.rules) {
    if ((r.action ?? '').toUpperCase() !== 'DENY') continue
    lines.push('')
    if (r.name || r.policy_id) lines.push(`// ${r.name ?? r.policy_id}`)
    lines.push('forbid (', `    principal == ${principal},`, '    action,', '    resource', ')')
    if (r.rule) {
      lines.push('when {', `    ${r.rule}`, '};')
    } else {
      lines[lines.length - 1] = ');'
    }
  }

  return lines.join('\n')
}

export function policyFilename(name: string, lang: PolicyLang): string {
  const base = (name || 'policy').replace(/[^a-z0-9_-]+/gi, '-').toLowerCase()
  return `${base}.${lang}`
}
