/**
 * Helpers to render a Cedar PolicyDetail across CEDAR / JSON / YAML views and to
 * extract its individual elements (effect, principal, action, resource, conditions)
 * for the visual breakdown. All parsing is best-effort and null-safe — live policy
 * content can be malformed or empty, and must never crash the view.
 */
import type { PolicyDetail } from '../types/api'

export type PolicyLang = 'cedar' | 'json' | 'yaml'

export interface CedarElements {
  effect: 'permit' | 'forbid' | null
  principal: string | null
  action: string | null
  resource: string | null
  conditions: string[]
}

export function parseCedarElements(content: unknown): CedarElements {
  const empty: CedarElements = {
    effect: null,
    principal: null,
    action: null,
    resource: null,
    conditions: [],
  }
  if (!content || typeof content !== 'string') return empty

  const text = content.trim()
  const clean = (s: string) => s.replace(/\s+/g, ' ').trim().replace(/[,;)]+$/, '')

  const effectMatch = text.match(/\b(permit|forbid)\b/i)
  const effect = effectMatch ? (effectMatch[1].toLowerCase() as 'permit' | 'forbid') : null

  const principalMatch = text.match(/principal\s+([^,\n)]+)/i)
  const resourceMatch = text.match(/resource\s+([^,\n)]+)/i)

  let action: string | null = null
  const actBracket = text.match(/action\s+in\s+\[([^\]]*)\]/i)
  if (actBracket) action = clean(actBracket[1])
  else {
    const actSimple = text.match(/action\s+([^,\n)]+)/i)
    if (actSimple) action = clean(actSimple[1])
  }

  const whenMatch = text.match(/when\s*\{([\s\S]*?)\}/i)
  const conditions = whenMatch
    ? whenMatch[1]
        .split('&&')
        .map((s) => s.replace(/\s+/g, ' ').trim())
        .filter(Boolean)
    : []

  return {
    effect,
    principal: principalMatch ? clean(principalMatch[1]) : null,
    action,
    resource: resourceMatch ? clean(resourceMatch[1]) : null,
    conditions,
  }
}

/**
 * Coerce policy content to a string. The DTO types it as `string`, but the live
 * `/v1/policies/{id}` response can return a structured object (S3 passthrough) or
 * null — passing that to `.split()`/`<pre>` crashes the viewer. Stringify safely.
 */
export function contentToString(content: unknown): string {
  if (content === null || content === undefined) return ''
  if (typeof content === 'string') return content
  try {
    return JSON.stringify(content, null, 2)
  } catch {
    return String(content)
  }
}

function policyToRecord(p: PolicyDetail) {
  return {
    policy_id: p.policy_id,
    name: p.name,
    status: p.status,
    version: p.version,
    agent_count: p.agent_count,
    updated_at: p.updated_at,
    s3_key: p.s3_key,
    content: contentToString(p.content),
  }
}

function yamlScalar(v: unknown): string {
  if (v === null || v === undefined) return 'null'
  if (typeof v === 'number' || typeof v === 'boolean') return String(v)
  const s = String(v)
  return /[:#\-?{}[\],&*!|>'"%@`]/.test(s) || s.trim() !== s ? JSON.stringify(s) : s
}

/** Render the policy in the requested language for the code viewer. */
export function renderPolicy(p: PolicyDetail, lang: PolicyLang): string {
  const content = contentToString(p.content)
  if (lang === 'cedar') return content || '// No policy content available'
  if (lang === 'json') return JSON.stringify(policyToRecord(p), null, 2)

  // yaml
  const rec = policyToRecord(p)
  return Object.entries(rec)
    .map(([k, v]) => {
      if (k === 'content') {
        const body = String(v)
        if (!body) return `${k}: ""`
        const indented = body.split('\n').map((l) => `  ${l}`).join('\n')
        return `${k}: |\n${indented}`
      }
      return `${k}: ${yamlScalar(v)}`
    })
    .join('\n')
}

export function policyFilename(name: string, lang: PolicyLang): string {
  const base = (name || 'policy').replace(/[^a-z0-9_-]+/gi, '-').toLowerCase()
  const ext = lang === 'cedar' ? 'cedar' : lang
  return `${base}.${ext}`
}
