import { useMemo, useState } from 'react'
import type { FlowGraph, FlowTone, SankeyLink, SankeyNode } from '../../lib/flowGraph'

const VBW = 1000
const NODE_W = 13
const GAP = 16
const PAD_Y = 12

const TONE_COLOR: Record<FlowTone, string> = {
  allow: '#0FFFFF',
  deny: '#FF0080',
  mixed: '#FFB020',
}
const NEUTRAL_NODE = '#4A5B66'

function nodeFill(tone?: FlowTone) {
  return tone ? TONE_COLOR[tone] : NEUTRAL_NODE
}

interface Placed extends SankeyNode {
  x: number
  y: number
  h: number
}
interface Ribbon {
  id: string
  tone: FlowTone
  d: string
  source: string
  target: string
  title: string
}

function pushTo<T>(map: Map<string, T[]>, key: string, val: T) {
  const arr = map.get(key)
  if (arr) arr.push(val)
  else map.set(key, [val])
}

function layout(graph: FlowGraph, height: number) {
  const { nodes, links } = graph
  const columns = [...new Set(nodes.map((n) => n.column))].sort((a, b) => a - b)
  const colCount = columns.length

  const outSum = new Map<string, number>()
  const inSum = new Map<string, number>()
  for (const l of links) {
    outSum.set(l.source, (outSum.get(l.source) ?? 0) + l.value)
    inSum.set(l.target, (inSum.get(l.target) ?? 0) + l.value)
  }
  const valueOf = (n: SankeyNode) => Math.max(outSum.get(n.id) ?? 0, inSum.get(n.id) ?? 0, 0)

  const byCol = new Map<number, SankeyNode[]>()
  for (const c of columns) byCol.set(c, [])
  for (const n of nodes) byCol.get(n.column)!.push(n)
  for (const c of columns) byCol.get(c)!.sort((a, b) => valueOf(b) - valueOf(a))

  const usableH = height - PAD_Y * 2
  let unit = Infinity
  for (const c of columns) {
    const list = byCol.get(c)!
    const total = list.reduce((s, n) => s + valueOf(n), 0)
    const gaps = Math.max(0, list.length - 1) * GAP
    if (total > 0) unit = Math.min(unit, (usableH - gaps) / total)
  }
  if (!Number.isFinite(unit) || unit <= 0) unit = 1

  const colX = (i: number) =>
    colCount <= 1 ? (VBW - NODE_W) / 2 : 16 + (VBW - 32 - NODE_W) * (i / (colCount - 1))

  const placed = new Map<string, Placed>()
  columns.forEach((c, ci) => {
    const list = byCol.get(c)!
    const gaps = Math.max(0, list.length - 1) * GAP
    const contentH = list.reduce((s, n) => s + Math.max(valueOf(n) * unit, 3), 0) + gaps
    let y = PAD_Y + Math.max(0, (usableH - contentH) / 2)
    for (const n of list) {
      const h = Math.max(valueOf(n) * unit, 3)
      placed.set(n.id, { ...n, x: colX(ci), y, h })
      y += h + GAP
    }
  })

  const labelOf = new Map(nodes.map((n) => [n.id, n.label]))
  const srcGroups = new Map<string, SankeyLink[]>()
  const tgtGroups = new Map<string, SankeyLink[]>()
  for (const l of links) {
    pushTo(srcGroups, l.source, l)
    pushTo(tgtGroups, l.target, l)
  }
  for (const [, list] of srcGroups) list.sort((a, b) => placed.get(a.target)!.y - placed.get(b.target)!.y)
  for (const [, list] of tgtGroups) list.sort((a, b) => placed.get(a.source)!.y - placed.get(b.source)!.y)

  const srcBand = new Map<string, [number, number]>()
  const tgtBand = new Map<string, [number, number]>()
  for (const [src, list] of srcGroups) {
    let cur = placed.get(src)!.y
    for (const l of list) {
      const h = l.value * unit
      srcBand.set(l.id, [cur, cur + h])
      cur += h
    }
  }
  for (const [tgt, list] of tgtGroups) {
    let cur = placed.get(tgt)!.y
    for (const l of list) {
      const h = l.value * unit
      tgtBand.set(l.id, [cur, cur + h])
      cur += h
    }
  }

  const ribbons: Ribbon[] = links.map((l) => {
    const s = placed.get(l.source)!
    const t = placed.get(l.target)!
    const [sy0, sy1] = srcBand.get(l.id)!
    const [ty0, ty1] = tgtBand.get(l.id)!
    const sx = s.x + NODE_W
    const tx = t.x
    const mx = (sx + tx) / 2
    const d = `M${sx},${sy0} C${mx},${sy0} ${mx},${ty0} ${tx},${ty0} L${tx},${ty1} C${mx},${ty1} ${mx},${sy1} ${sx},${sy1} Z`
    return {
      id: l.id,
      tone: l.tone,
      d,
      source: l.source,
      target: l.target,
      title: `${labelOf.get(l.source)} \u2192 ${labelOf.get(l.target)} \u00b7 ${l.value}`,
    }
  })

  return { placed: [...placed.values()], ribbons }
}

interface FlowSankeyProps {
  graph: FlowGraph
  /** Links on the heat path — emphasized; everything else dims. */
  heatLinkIds?: Set<string>
  height?: number
}

/** Read-only layered flow (Sankey) diagram rendered as inline SVG. */
export function FlowSankey({ graph, heatLinkIds, height = 380 }: FlowSankeyProps) {
  const [hovered, setHovered] = useState<string | null>(null)
  const { placed, ribbons } = useMemo(() => layout(graph, height), [graph, height])

  const hasHeat = !!heatLinkIds && heatLinkIds.size > 0
  const heatNodeIds = useMemo(() => {
    const s = new Set<string>()
    if (heatLinkIds) {
      for (const r of ribbons) {
        if (heatLinkIds.has(r.id)) {
          s.add(r.source)
          s.add(r.target)
        }
      }
    }
    return s
  }, [ribbons, heatLinkIds])

  if (placed.length === 0) return null
  const lastCol = Math.max(...placed.map((n) => n.column))

  const ribbonOpacity = (r: Ribbon) => {
    if (hovered) return r.source === hovered || r.target === hovered ? 0.72 : 0.07
    if (hasHeat) return heatLinkIds!.has(r.id) ? 0.6 : 0.12
    return 0.3
  }

  return (
    <svg viewBox={`0 0 ${VBW} ${height}`} width="100%" height={height} role="img" aria-label="Flow diagram">
      <g>
        {ribbons.map((r) => (
          <path key={r.id} d={r.d} fill={TONE_COLOR[r.tone]} opacity={ribbonOpacity(r)} style={{ transition: 'opacity .2s' }}>
            <title>{r.title}</title>
          </path>
        ))}
      </g>
      <g>
        {placed.map((n) => {
          const isLast = n.column === lastCol
          const labelX = isLast ? n.x - 8 : n.x + NODE_W + 8
          const anchor = isLast ? 'end' : 'start'
          const onHeat = heatNodeIds.has(n.id)
          const dimNode = hasHeat && !onHeat && hovered !== n.id
          const labelFill = hovered === n.id || onHeat ? '#E6F1F5' : '#8DA2AE'
          return (
            <g key={n.id} onMouseEnter={() => setHovered(n.id)} onMouseLeave={() => setHovered(null)}>
              <rect x={n.x} y={n.y} width={NODE_W} height={n.h} rx={3} fill={nodeFill(n.tone)} opacity={dimNode ? 0.45 : 0.92} />
              <text
                x={labelX}
                y={n.y + n.h / 2}
                textAnchor={anchor}
                dominantBaseline="middle"
                fontSize={13}
                fontFamily="'IBM Plex Mono', monospace"
                fill={labelFill}
                style={{ paintOrder: 'stroke', stroke: '#010B13', strokeWidth: 3 }}
              >
                {n.label}
                {n.sublabel && (
                  <tspan fill="#51636E" dx={6}>
                    {n.sublabel}
                  </tspan>
                )}
              </text>
            </g>
          )
        })}
      </g>
    </svg>
  )
}
