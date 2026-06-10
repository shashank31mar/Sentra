/**
 * Flow-graph aggregation for the Topology (fleet) and per-agent Flow views.
 *
 * Both views render a layered Sankey: nodes are bucketed into ordered `column`s
 * and `links` carry a weight (observed decision volume) plus a tone (allow /
 * deny / mixed). All inputs are best-effort and null-safe — live decision data
 * can have missing tool names, unknown agents, etc., and must never throw.
 */
import type { DecisionItem } from '../types/api'

export type FlowTone = 'allow' | 'deny' | 'mixed'

export interface SankeyNode {
  id: string
  label: string
  /** Small dim suffix shown next to the label (e.g. a count). */
  sublabel?: string
  column: number
  tone?: FlowTone
}

export interface SankeyLink {
  id: string
  source: string
  target: string
  value: number
  tone: FlowTone
}

export interface FlowGraph {
  nodes: SankeyNode[]
  links: SankeyLink[]
}

interface Acc {
  allow: number
  deny: number
}

function bump(map: Map<string, Acc>, key: string, deny: boolean) {
  const a = map.get(key) ?? { allow: 0, deny: 0 }
  if (deny) a.deny += 1
  else a.allow += 1
  map.set(key, a)
}

function toneOf(allow: number, deny: number): FlowTone {
  if (allow > 0 && deny > 0) return 'mixed'
  return deny > 0 ? 'deny' : 'allow'
}

function pushTo<T>(map: Map<string, T[]>, key: string, val: T) {
  const arr = map.get(key)
  if (arr) arr.push(val)
  else map.set(key, [val])
}

/**
 * Fleet topology: Cloud → Agent → Tool, weighted by decision volume. Tool nodes
 * are shared across agents so convergence (a tool used by many agents) reads as
 * a funnel. Limited to the `topAgents` busiest agents to keep it legible.
 */
export function buildFleetFlow(decisions: DecisionItem[], topAgents = 12): FlowGraph {
  const agentTotals = new Map<string, number>()
  for (const d of decisions) agentTotals.set(d.agent_id, (agentTotals.get(d.agent_id) ?? 0) + 1)

  const kept = new Set(
    [...agentTotals.entries()]
      .sort((a, b) => b[1] - a[1])
      .slice(0, Math.max(1, topAgents))
      .map(([id]) => id),
  )
  const rows = decisions.filter((d) => kept.has(d.agent_id))

  const cloudAcc = new Map<string, Acc>()
  const toolAcc = new Map<string, Acc>()
  const cloudAgent = new Map<string, Acc>()
  const agentTool = new Map<string, Acc>()
  const agentMeta = new Map<string, { name: string; cloud: string; total: number }>()

  for (const d of rows) {
    const tool = d.tool_name ?? 'unknown'
    const deny = d.decision === 'DENY'
    const meta = agentMeta.get(d.agent_id) ?? { name: d.agent_name, cloud: d.cloud_provider, total: 0 }
    meta.total += 1
    agentMeta.set(d.agent_id, meta)
    bump(cloudAcc, d.cloud_provider, deny)
    bump(toolAcc, tool, deny)
    bump(cloudAgent, `${d.cloud_provider}\u0000${d.agent_id}`, deny)
    bump(agentTool, `${d.agent_id}\u0000${tool}`, deny)
  }

  const nodes: SankeyNode[] = []
  const links: SankeyLink[] = []

  for (const [cloud, acc] of cloudAcc) {
    nodes.push({ id: `cloud:${cloud}`, label: cloud.toUpperCase(), sublabel: String(acc.allow + acc.deny), column: 0, tone: toneOf(acc.allow, acc.deny) })
  }
  for (const [agentId, meta] of agentMeta) {
    nodes.push({ id: `agent:${agentId}`, label: meta.name, sublabel: String(meta.total), column: 1 })
  }
  for (const [tool, acc] of toolAcc) {
    nodes.push({ id: `tool:${tool}`, label: tool, sublabel: String(acc.allow + acc.deny), column: 2, tone: toneOf(acc.allow, acc.deny) })
  }

  for (const [key, acc] of cloudAgent) {
    const [cloud, agentId] = key.split('\u0000')
    links.push({ id: `ca:${key}`, source: `cloud:${cloud}`, target: `agent:${agentId}`, value: acc.allow + acc.deny, tone: toneOf(acc.allow, acc.deny) })
  }
  for (const [key, acc] of agentTool) {
    const [agentId, tool] = key.split('\u0000')
    links.push({ id: `at:${key}`, source: `agent:${agentId}`, target: `tool:${tool}`, value: acc.allow + acc.deny, tone: toneOf(acc.allow, acc.deny) })
  }

  return { nodes, links }
}

/**
 * Per-agent flow: Agent → Tool → Outcome (Allowed / Blocked). Shows which tools
 * the agent leans on (heat path) and how each one resolves against policy.
 */
export function buildAgentFlow(decisions: DecisionItem[], agentId: string, agentName: string): FlowGraph {
  const rows = decisions.filter((d) => d.agent_id === agentId)
  const toolAcc = new Map<string, Acc>()
  for (const d of rows) bump(toolAcc, d.tool_name ?? 'unknown', d.decision === 'DENY')

  const nodes: SankeyNode[] = [{ id: `agent:${agentId}`, label: agentName, sublabel: String(rows.length), column: 0 }]
  const links: SankeyLink[] = []
  let allowTotal = 0
  let denyTotal = 0

  for (const [tool, acc] of toolAcc) {
    const total = acc.allow + acc.deny
    nodes.push({ id: `tool:${tool}`, label: tool, sublabel: String(total), column: 1, tone: toneOf(acc.allow, acc.deny) })
    links.push({ id: `at:${tool}`, source: `agent:${agentId}`, target: `tool:${tool}`, value: total, tone: toneOf(acc.allow, acc.deny) })
    if (acc.allow > 0) {
      links.push({ id: `oa:${tool}`, source: `tool:${tool}`, target: 'out:allow', value: acc.allow, tone: 'allow' })
      allowTotal += acc.allow
    }
    if (acc.deny > 0) {
      links.push({ id: `od:${tool}`, source: `tool:${tool}`, target: 'out:deny', value: acc.deny, tone: 'deny' })
      denyTotal += acc.deny
    }
  }
  if (allowTotal > 0) nodes.push({ id: 'out:allow', label: 'Allowed', sublabel: String(allowTotal), column: 2, tone: 'allow' })
  if (denyTotal > 0) nodes.push({ id: 'out:deny', label: 'Blocked', sublabel: String(denyTotal), column: 2, tone: 'deny' })

  return { nodes, links }
}

export interface HeatPath {
  linkIds: Set<string>
  nodeIds: Set<string>
  labels: string[]
  /** Bottleneck volume along the path (min link value). */
  value: number
}

/**
 * The single hottest end-to-end route: seed on the heaviest link, then extend
 * greedily forward and backward through the heaviest connected links.
 */
export function computeHeatPath(graph: FlowGraph): HeatPath | null {
  const { nodes, links } = graph
  if (links.length === 0) return null

  const labelOf = new Map(nodes.map((n) => [n.id, n.label]))
  const outByNode = new Map<string, SankeyLink[]>()
  const inByNode = new Map<string, SankeyLink[]>()
  for (const l of links) {
    pushTo(outByNode, l.source, l)
    pushTo(inByNode, l.target, l)
  }

  const seed = links.reduce((m, l) => (l.value > m.value ? l : m), links[0])
  const chain: SankeyLink[] = [seed]
  const seen = new Set<string>([seed.source, seed.target])

  let cur = seed.target
  for (;;) {
    const outs = (outByNode.get(cur) ?? []).filter((l) => !seen.has(l.target))
    if (outs.length === 0) break
    const next = outs.reduce((m, l) => (l.value > m.value ? l : m))
    chain.push(next)
    seen.add(next.target)
    cur = next.target
  }

  cur = seed.source
  for (;;) {
    const ins = (inByNode.get(cur) ?? []).filter((l) => !seen.has(l.source))
    if (ins.length === 0) break
    const prev = ins.reduce((m, l) => (l.value > m.value ? l : m))
    chain.unshift(prev)
    seen.add(prev.source)
    cur = prev.source
  }

  const linkIds = new Set(chain.map((l) => l.id))
  const nodeIds = new Set<string>()
  const labels: string[] = []
  chain.forEach((l, i) => {
    nodeIds.add(l.source)
    nodeIds.add(l.target)
    if (i === 0) labels.push(labelOf.get(l.source) ?? l.source)
    labels.push(labelOf.get(l.target) ?? l.target)
  })

  return { linkIds, nodeIds, labels, value: Math.min(...chain.map((l) => l.value)) }
}
