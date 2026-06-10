/**
 * Render a Sentra agent policy's content for the source viewer (YAML / JSON) and a couple of
 * small helpers. Sentra policies are agent YAML configs (allowed_tools, cross_cloud_dependencies,
 * inner rules, rate limit) — NOT Cedar — so the viewer shows the real authored YAML and its JSON.
 * All parsing is best-effort and null-safe: live content can be an object, a string, or null.
 */
export type PolicyLang = 'yaml' | 'json'

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

export function policyFilename(name: string, lang: PolicyLang): string {
  const base = (name || 'policy').replace(/[^a-z0-9_-]+/gi, '-').toLowerCase()
  return `${base}.${lang}`
}
