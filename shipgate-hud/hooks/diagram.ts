// The diagram core (ADR 0002): a section's markdown split at its `mermaid` / `svg` fences, the
// Mermaid flowchart subset parsed into nodes and edges, a layered layout, and two drawings of
// it: an SVG document for surfaces with `Svg` and a box-and-arrow text form for the terminal.
// No `$` here, so the tests run it without a process or a file system.

export type Fence = { kind: 'markdown'; text: string } | { kind: 'fence'; lang: 'mermaid' | 'svg'; source: string }

const FENCE_OPEN = /^\s{0,3}(`{3,}|~{3,})\s*([^\s`]*)/

/** A section's markdown split at its ```mermaid and ```svg fences; every other fence stays inside the markdown chunks. */
export function splitFences(markdown: string): Fence[] {
  const out: Fence[] = []
  const lines = markdown.split('\n')
  let text: string[] = []
  const flush = (): void => {
    if (text.join('\n').trim() !== '') out.push({ kind: 'markdown', text: text.join('\n') })
    text = []
  }
  let i = 0
  while (i < lines.length) {
    const line = lines[i] ?? ''
    const open = FENCE_OPEN.exec(line)
    if (!open) {
      text.push(line)
      i++
      continue
    }
    const marker = open[1] ?? '```'
    const lang = (open[2] ?? '').toLowerCase()
    const close = new RegExp(`^\\s{0,3}${marker[0] === '`' ? '`' : '~'}{${marker.length},}\\s*$`)
    let end = i + 1
    while (end < lines.length && !close.test(lines[end] ?? '')) end++
    if ((lang === 'mermaid' || lang === 'svg') && end < lines.length) {
      flush()
      out.push({ kind: 'fence', lang, source: lines.slice(i + 1, end).join('\n') })
    } else {
      text.push(...lines.slice(i, Math.min(end + 1, lines.length)))
    }
    i = end + 1
  }
  flush()
  return out
}

export type Direction = 'LR' | 'TD' | 'TB' | 'RL' | 'BT'
export type NodeShape = 'rect' | 'round' | 'diamond' | 'circle'
export type FlowNode = { id: string; label: string; shape: NodeShape }
export type EdgeStyle = 'solid' | 'dotted' | 'thick' | 'open'
export type FlowEdge = { from: string; to: string; label: string; style: EdgeStyle }
export type Flowchart = { direction: Direction; nodes: FlowNode[]; edges: FlowEdge[] }

const DIRECTIONS: readonly Direction[] = ['LR', 'TD', 'TB', 'RL', 'BT']
// a keyword alone, not the start of an id such as `end-user` or `style-guide`
const SKIPPED = /^(subgraph|end|classDef|class|style|click|linkStyle|direction)(?=\s|;|$)/

/** Inner label text: trimmed, `<br/>` as a space, surrounding quotes removed. */
export function cleanLabel(raw: string): string {
  const text = raw.replace(/<br\s*\/?>/gi, ' ').trim()
  const unquoted = /^"(.*)"$/.exec(text)?.[1] ?? text
  return unquoted.replace(/\s+/g, ' ').trim()
}

type NodeRef = { id: string; label: string | null; shape: NodeShape }

const NODE_ID = /^\s*([\w]+(?:-[\w]+)*)/
// doubled forms first, each mapped to the nearest shape the HUD draws
const SHAPES: readonly [RegExp, NodeShape][] = [
  [/^\(\((.*?)\)\)/, 'circle'],
  [/^\[\[(.*?)\]\]/, 'rect'],
  [/^\{\{(.*?)\}\}/, 'diamond'],
  [/^\[\((.*?)\)\]/, 'round'],
  [/^\(\[(.*?)\]\)/, 'round'],
  [/^>(.*?)\]/, 'rect'],
  [/^\["(.*?)"\]/, 'rect'],
  [/^\[(.*?)\]/, 'rect'],
  [/^\("(.*?)"\)/, 'round'],
  [/^\((.*?)\)/, 'round'],
  [/^\{(.*?)\}/, 'diamond'],
]

const readNode = (text: string): { node: NodeRef; rest: string } | null => {
  const id = NODE_ID.exec(text)
  if (!id?.[1]) return null
  let rest = text.slice(id[0].length)
  let node: NodeRef = { id: id[1], label: null, shape: 'rect' }
  for (const [re, shape] of SHAPES) {
    const m = re.exec(rest)
    if (m) {
      node = { id: id[1], label: cleanLabel(m[1] ?? ''), shape }
      rest = rest.slice(m[0].length)
      break
    }
  }
  rest = rest.replace(/^:::[\w-]+/, '')
  return { node, rest }
}

const readGroup = (text: string): { nodes: NodeRef[]; rest: string } | null => {
  const first = readNode(text)
  if (!first) return null
  const nodes = [first.node]
  let rest = first.rest
  for (;;) {
    const amp = /^\s*&\s*/.exec(rest)
    if (!amp) break
    const next = readNode(rest.slice(amp[0].length))
    if (!next) break
    nodes.push(next.node)
    rest = next.rest
  }
  return { nodes, rest }
}

const styleOf = (op: string): EdgeStyle =>
  op.includes('.') ? 'dotted' : op.includes('=') ? 'thick' : op.endsWith('>') ? 'solid' : 'open'

const PLAIN_OP = /^\s*(-{2,}>|-{3,}|-\.+->|-\.+-|={2,}>|={3,})/
const LABELLED_OPS: readonly RegExp[] = [
  /^\s*--\s*([^\s\->|].*?)\s*(-{2,}>|-{3,})/,
  /^\s*-\.\s*([^\s\->|.].*?)\s*(\.+->|\.+-)/,
  /^\s*==\s*([^\s=>|].*?)\s*(={2,}>|={3,})/,
]

const readEdge = (text: string): { label: string; style: EdgeStyle; rest: string } | null => {
  const plain = PLAIN_OP.exec(text)
  if (plain?.[1]) {
    let rest = text.slice(plain[0].length)
    let label = ''
    const piped = /^\s*\|([^|]*)\|/.exec(rest)
    if (piped) {
      label = cleanLabel(piped[1] ?? '')
      rest = rest.slice(piped[0].length)
    }
    return { label, style: styleOf(plain[1]), rest }
  }
  for (const re of LABELLED_OPS) {
    const m = re.exec(text)
    if (m) {
      const style = styleOf(`${text.trimStart().slice(0, 2)}${m[2] ?? ''}`)
      return { label: cleanLabel(m[1] ?? ''), style, rest: text.slice(m[0].length) }
    }
  }
  return null
}

/**
 * The Mermaid flowchart subset parsed, or null when the source is not a flowchart
 * (`sequenceDiagram`, `classDiagram`, …), nothing parses, or a statement leaves text it could
 * not read (a drawing that silently dropped an edge would mislead; the block falls back to code).
 */
export function parseFlowchart(source: string): Flowchart | null {
  const lines = source
    .split('\n')
    .map(l => l.trim())
    .filter(l => l !== '' && !l.startsWith('%%'))
  // `graph TD; A-->B` carries statements on the header line, after its first `;`
  const first = lines[0] ?? ''
  const semi = first.indexOf(';')
  const statements = semi === -1 ? lines.slice(1) : [first.slice(semi + 1), ...lines.slice(1)]
  const header = (semi === -1 ? first : first.slice(0, semi)).split(/\s+/)
  const kind = header[0]
  if (kind !== 'flowchart' && kind !== 'graph') return null
  const dir = (header[1] ?? '').toUpperCase()
  const direction: Direction = (DIRECTIONS as readonly string[]).includes(dir) ? (dir as Direction) : 'TD'

  const nodes = new Map<string, FlowNode & { declared: boolean }>()
  const edges: FlowEdge[] = []
  const see = (ref: NodeRef): void => {
    const known = nodes.get(ref.id)
    if (!known) nodes.set(ref.id, { id: ref.id, label: ref.label ?? ref.id, shape: ref.shape, declared: ref.label !== null })
    else if (!known.declared && ref.label !== null) Object.assign(known, { label: ref.label, shape: ref.shape, declared: true })
  }

  for (const line of statements) {
    for (const statement of line.split(';')) {
      if (statement.trim() === '' || SKIPPED.test(statement.trim())) continue
      let group = readGroup(statement)
      // a statement the HUD cannot start reading would drop its edges silently: fall back to code
      if (!group) return null
      group.nodes.forEach(see)
      let rest = group.rest
      for (;;) {
        const edge = readEdge(group.rest)
        if (!edge) break
        const next = readGroup(edge.rest)
        if (!next) break
        next.nodes.forEach(see)
        for (const from of group.nodes)
          for (const to of next.nodes) edges.push({ from: from.id, to: to.id, label: edge.label, style: edge.style })
        group = next
        rest = next.rest
      }
      if (rest.trim() !== '') return null
    }
  }
  if (nodes.size === 0) return null
  return { direction, nodes: [...nodes.values()].map(({ id, label, shape }) => ({ id, label, shape })), edges }
}

export type Box = { x: number; y: number; w: number; h: number }
export type Layout = { layers: string[][]; width: number; height: number; boxes: Record<string, Box> }

const BOX_W = 120
const BOX_H = 36
const GAP = 40
const MARGIN = 20
const CHAR_W = 7.5

const horizontal = (direction: Direction): boolean => direction === 'LR' || direction === 'RL'

/** The box width for a label: 120, wider for long labels. */
export const boxWidth = (label: string): number => Math.max(BOX_W, Math.ceil([...label].length * CHAR_W) + 24)

/** Layers by longest path from the sources (cycles broken by first-seen order), nodes in first-seen order within a layer; pixel boxes for the SVG. */
export function layoutFlowchart(chart: Flowchart): Layout {
  const order = chart.nodes.map(n => n.id)
  const out = new Map<string, string[]>(order.map(id => [id, []]))
  for (const e of chart.edges) out.get(e.from)?.push(e.to)

  // Drop back edges found by a depth-first walk in first-seen order.
  const state = new Map<string, 'open' | 'done'>()
  const forward = new Map<string, string[]>(order.map(id => [id, []]))
  const walk = (id: string): void => {
    state.set(id, 'open')
    for (const to of out.get(id) ?? []) {
      if (state.get(to) === 'open') continue
      forward.get(id)?.push(to)
      if (!state.has(to)) walk(to)
    }
    state.set(id, 'done')
  }
  for (const id of order) if (!state.has(id)) walk(id)

  // Longest path over the acyclic edges, relaxed in topological order.
  const indegree = new Map<string, number>(order.map(id => [id, 0]))
  for (const tos of forward.values()) for (const to of tos) indegree.set(to, (indegree.get(to) ?? 0) + 1)
  const layer = new Map<string, number>(order.map(id => [id, 0]))
  const queue = order.filter(id => indegree.get(id) === 0)
  while (queue.length > 0) {
    const id = queue.shift() as string
    for (const to of forward.get(id) ?? []) {
      layer.set(to, Math.max(layer.get(to) ?? 0, (layer.get(id) ?? 0) + 1))
      indegree.set(to, (indegree.get(to) ?? 0) - 1)
      if (indegree.get(to) === 0) queue.push(to)
    }
  }
  const layers: string[][] = []
  for (const id of order) {
    const l = layer.get(id) ?? 0
    while (layers.length <= l) layers.push([])
    layers[l]?.push(id)
  }

  // Pixels: the main axis runs along the layers, the cross axis within one.
  const labels = new Map(chart.nodes.map(n => [n.id, n.label]))
  const flat = horizontal(chart.direction)
  const size = (id: string): { w: number; h: number } => ({ w: boxWidth(labels.get(id) ?? id), h: BOX_H })
  const along = (s: { w: number; h: number }): number => (flat ? s.w : s.h)
  const across = (s: { w: number; h: number }): number => (flat ? s.h : s.w)
  const thickness = layers.map(ids => Math.max(...ids.map(id => along(size(id)))))
  const spans = layers.map(ids => ids.reduce((sum, id) => sum + across(size(id)), 0) + GAP * (ids.length - 1))
  const crossTotal = Math.max(0, ...spans)
  const mainTotal = thickness.reduce((a, b) => a + b, 0) + GAP * Math.max(0, layers.length - 1)
  const reversed = chart.direction === 'RL' || chart.direction === 'BT'

  const boxes: Record<string, Box> = {}
  let main = 0
  layers.forEach((ids, l) => {
    const t = thickness[l] ?? 0
    let cross = ((crossTotal - (spans[l] ?? 0)) / 2)
    for (const id of ids) {
      const s = size(id)
      const m = reversed ? mainTotal - main - t : main
      const a = m + (t - along(s)) / 2
      boxes[id] = flat ? { x: MARGIN + a, y: MARGIN + cross, w: s.w, h: s.h } : { x: MARGIN + cross, y: MARGIN + a, w: s.w, h: s.h }
      cross += across(s) + GAP
    }
    main += t + GAP
  })
  const width = Math.ceil((flat ? mainTotal : crossTotal) + 2 * MARGIN)
  const height = Math.ceil((flat ? crossTotal : mainTotal) + 2 * MARGIN)
  return { layers, width, height, boxes }
}

const escapeXml = (text: string): string =>
  text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')

const num = (n: number): string => String(Math.round(n * 10) / 10)

/** The point where the line from a box's centre toward (tx, ty) leaves the box. */
const exitPoint = (b: Box, tx: number, ty: number): [number, number] => {
  const cx = b.x + b.w / 2
  const cy = b.y + b.h / 2
  const dx = tx - cx
  const dy = ty - cy
  if (dx === 0 && dy === 0) return [cx, cy]
  const t = Math.min(dx === 0 ? Infinity : b.w / 2 / Math.abs(dx), dy === 0 ? Infinity : b.h / 2 / Math.abs(dy))
  return [cx + dx * t, cy + dy * t]
}

/** FNV-1a over the UTF-16 units, as 8 hex digits: a short stable id, not a security hash. */
const hashOf = (text: string): string => {
  let h = 0x811c9dc5
  for (let i = 0; i < text.length; i++) h = Math.imul(h ^ text.charCodeAt(i), 0x01000193)
  return (h >>> 0).toString(16).padStart(8, '0')
}

const RADIUS: Record<NodeShape, number> = { rect: 4, round: 18, diamond: 4, circle: 18 }

/** An `<svg …>…</svg>` document: rounded rects (120 wide, wider for long labels, 36 high, 40 px gaps), lines with an arrowhead marker (none for `open` edges, dashed for `dotted`, thicker for `thick`), edge labels at the midpoint, oriented LR/RL (layers left to right) or TD/TB/BT (top to bottom). */
export function flowchartSvg(chart: Flowchart, layout: Layout = layoutFlowchart(chart)): string {
  // per chart, so two drawings on one page never share (and restyle) one another's arrowhead
  const marker = `arrow-${hashOf(JSON.stringify(chart))}`
  const parts: string[] = [
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${layout.width} ${layout.height}" width="${layout.width}" height="${layout.height}" font-family="sans-serif" font-size="13">`,
    `<defs><marker id="${marker}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="#52525b"/></marker></defs>`,
  ]
  const labels: string[] = []
  for (const e of chart.edges) {
    const from = layout.boxes[e.from]
    const to = layout.boxes[e.to]
    if (!from || !to) continue
    const [x1, y1] = exitPoint(from, to.x + to.w / 2, to.y + to.h / 2)
    const [x2, y2] = exitPoint(to, from.x + from.w / 2, from.y + from.h / 2)
    const attrs = [
      `x1="${num(x1)}" y1="${num(y1)}" x2="${num(x2)}" y2="${num(y2)}" stroke="#52525b"`,
      `stroke-width="${e.style === 'thick' ? 3 : 1.5}"`,
      e.style === 'dotted' ? 'stroke-dasharray="4 3"' : '',
      e.style === 'open' ? '' : `marker-end="url(#${marker})"`,
    ]
    parts.push(`<line ${attrs.filter(a => a !== '').join(' ')}/>`)
    if (e.label !== '')
      labels.push(
        `<text x="${num((x1 + x2) / 2)}" y="${num((y1 + y2) / 2 - 4)}" text-anchor="middle" fill="#18181b" stroke="#ffffff" stroke-width="4" paint-order="stroke">${escapeXml(e.label)}</text>`,
      )
  }
  for (const n of chart.nodes) {
    const b = layout.boxes[n.id]
    if (!b) continue
    const r = RADIUS[n.shape]
    parts.push(
      `<rect x="${num(b.x)}" y="${num(b.y)}" width="${num(b.w)}" height="${num(b.h)}" rx="${r}" fill="#f4f4f5" stroke="#52525b"${n.shape === 'diamond' ? ' stroke-width="2"' : ''}/>`,
      `<text x="${num(b.x + b.w / 2)}" y="${num(b.y + b.h / 2)}" text-anchor="middle" dominant-baseline="central" fill="#18181b">${escapeXml(n.label)}</text>`,
    )
  }
  return [...parts, ...labels, '</svg>'].join('')
}

const TEXT_LIMIT = 24

/** `text` cut to `width` code points, the last one an ellipsis when it was longer; its spacing is kept. */
export const cut = (text: string, width: number): string => {
  const chars = [...text]
  return chars.length <= width ? text : `${chars.slice(0, Math.max(0, width - 1)).join('')}…`
}

/** A label cut to 24 cells, the last one an ellipsis when it was longer. */
export const cutLabel = (label: string): string => cut(label, TEXT_LIMIT)

const ARROW: Record<EdgeStyle, { line: string; head: string }> = {
  solid: { line: '──', head: '►' },
  dotted: { line: '┄┄', head: '►' },
  thick: { line: '══', head: '►' },
  open: { line: '──', head: '─' },
}

const arrowOf = (e: FlowEdge): string => {
  const { line, head } = ARROW[e.style]
  return e.label === '' ? `${line}${head}` : `${line}${cutLabel(e.label)}${line}${head === '─' ? '' : head}`
}

/** The terminal form: one line per layer with its nodes as `[label]` joined by three spaces; after each layer, one line per outgoing edge `[A] ──► [B]` or `[A] ──label──► [B]` (`┄┄►` for dotted, `══►` for thick, `───` without a head for open). Labels cut to 24 cells with an ellipsis. */
export function flowchartText(chart: Flowchart, layout: Layout = layoutFlowchart(chart)): string {
  const labels = new Map(chart.nodes.map(n => [n.id, n.label]))
  const box = (id: string): string => `[${cutLabel(labels.get(id) ?? id)}]`
  const lines: string[] = []
  for (const ids of layout.layers) {
    lines.push(ids.map(box).join('   '))
    for (const id of ids)
      for (const e of chart.edges) if (e.from === id) lines.push(`${box(e.from)} ${arrowOf(e)} ${box(e.to)}`)
  }
  return lines.join('\n')
}
