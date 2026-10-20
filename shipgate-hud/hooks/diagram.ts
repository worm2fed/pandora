// The diagram core (ADR 0002): a section's markdown split at its `mermaid` / `svg` fences, the
// Mermaid flowchart subset parsed into nodes and edges, a layered layout, and three drawings
// of it: an SVG document for surfaces with `Svg`, a box-drawing grid for the terminal (ADR
// 0003), and a one-line-per-edge text form, the terminal's fallback.
// No `$` here, so the tests run it without a process or a file system.

/** A chunk of a section's markdown: prose, or a `mermaid` / `svg` fence's source. */
export type Fence = { readonly kind: 'markdown'; readonly text: string } | { readonly kind: 'fence'; readonly lang: 'mermaid' | 'svg'; readonly source: string }

const FENCE_OPEN = /^\s{0,3}(`{3,}|~{3,})\s*([^\s`]*)/

/** A section's markdown split at its ```mermaid and ```svg fences; every other fence stays inside the markdown chunks. */
export function splitFences(markdown: string): readonly Fence[] {
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
export interface FlowNode {
  readonly id: string
  readonly label: string
  readonly shape: NodeShape
}
export type EdgeStyle = 'solid' | 'dotted' | 'thick' | 'open'
export interface FlowEdge {
  readonly from: string
  readonly to: string
  readonly label: string
  readonly style: EdgeStyle
}
export interface Flowchart {
  readonly direction: Direction
  readonly nodes: readonly FlowNode[]
  readonly edges: readonly FlowEdge[]
}

const DIRECTIONS: readonly Direction[] = ['LR', 'TD', 'TB', 'RL', 'BT']
// a keyword alone, not the start of an id such as `end-user` or `style-guide`
const SKIPPED = /^(subgraph|end|classDef|class|style|click|linkStyle|direction)(?=\s|;|$)/

// a whole CSI escape sequence (ESC [ or C1 CSI, parameters, final byte), then any other C0, DEL
// or C1 character: the class `stripControl` in review.ts removes; kept here so this file stays pure
const CSI = /(?:\u001b\[|\u009b)[0-?]*[ -/]*[@-~]/g
const CONTROL = /[\u0000-\u001f\u007f-\u009f]/g

/** Inner label text: trimmed, `<br/>` as a space, escape sequences and control characters out, surrounding quotes removed. */
export function cleanLabel(raw: string): string {
  const text = raw.replace(/<br\s*\/?>/gi, ' ').replace(CSI, '').replace(CONTROL, '').trim()
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
  const direction: Direction = DIRECTIONS.find(known => known === dir) ?? 'TD'

  const nodes = new Map<string, FlowNode & { readonly declared: boolean }>()
  const edges: FlowEdge[] = []
  const see = (ref: NodeRef): void => {
    const known = nodes.get(ref.id)
    if (!known) nodes.set(ref.id, { id: ref.id, label: ref.label ?? ref.id, shape: ref.shape, declared: ref.label !== null })
    else if (!known.declared && ref.label !== null) nodes.set(ref.id, { id: ref.id, label: ref.label, shape: ref.shape, declared: true })
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

export interface Box {
  readonly x: number
  readonly y: number
  readonly w: number
  readonly h: number
}
export interface Layout {
  readonly layers: readonly (readonly string[])[]
  readonly width: number
  readonly height: number
  readonly boxes: Readonly<Record<string, Box>>
}

const BOX_W = 120
const BOX_H = 36
const GAP = 40
const MARGIN = 20
const CHAR_W = 7.5

const horizontal = (direction: Direction): boolean => direction === 'LR' || direction === 'RL'

/** The box width for a label: 120, wider for long labels. */
export const boxWidth = (label: string): number => Math.max(BOX_W, Math.ceil([...label].length * CHAR_W) + 24)

// STATEFUL EXCEPTION (HUD ADR 0006): the layout and the terminal grid router below are graph
// walks and a cell canvas, written as loops over local Maps and arrays that they mutate in
// place. That state never leaves the call: each function returns fresh values, and the rest
// of the module (and the HUD) sees only readonly ones.

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
  // a for…of over an array visits what the loop pushes onto it: a queue without a shift
  for (const id of queue) {
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

/** One edge in the terminal's one-line form: `[A] ──► [B]`, `[A] ──label──► [B]`, `┄┄►` dotted, `══►` thick, `───` open; labels cut to 24 cells. */
export function edgeLine(chart: Flowchart, e: FlowEdge): string {
  const label = (id: string): string => `[${cutLabel(chart.nodes.find(n => n.id === id)?.label ?? id)}]`
  return `${label(e.from)} ${arrowOf(e)} ${label(e.to)}`
}

/** The terminal form: one line per layer with its nodes as `[label]` joined by three spaces; after each layer, one line per outgoing edge `[A] ──► [B]` or `[A] ──label──► [B]` (`┄┄►` for dotted, `══►` for thick, `───` without a head for open). Labels cut to 24 cells with an ellipsis. */
export function flowchartText(chart: Flowchart, layout: Layout = layoutFlowchart(chart)): string {
  const labels = new Map(chart.nodes.map(n => [n.id, n.label]))
  const box = (id: string): string => `[${cutLabel(labels.get(id) ?? id)}]`
  const lines: string[] = []
  for (const ids of layout.layers) {
    lines.push(ids.map(box).join('   '))
    for (const id of ids) for (const e of chart.edges) if (e.from === id) lines.push(edgeLine(chart, e))
  }
  return lines.join('\n')
}

// ── The terminal grid (ADR 0003) ─────────────────────────────────────────────────────────

/** Past this many nodes a terminal picture is unreadable; the caller draws the text form. */
export const GRID_NODE_LIMIT = 60
/** Past this many forward legs (each forward edge counts the layers it spans) the grid is skipped. */
export const GRID_LEG_LIMIT = 200
/** Past this many cells (width × height, projected before any cell is allocated) the grid is skipped. */
export const GRID_CELL_LIMIT = 40000
/** Past this many rows a terminal picture is too tall to read; the caller draws the text form. */
export const GRID_ROW_LIMIT = 200

/** The terminal picture: rows of cells, each exactly `width` code points; the back edges it did not route. */
export interface FlowGrid {
  readonly rows: readonly string[]
  readonly backEdges: readonly FlowEdge[]
  readonly width: number
}

/**
 * Why `flowchartGrid` drew no picture: too many nodes, too many forward legs, too many cells,
 * or a box or a label that would land outside the grid, on fixed text or on a line (`overlap`:
 * a broken router invariant, drawn as the text form rather than as a broken picture).
 */
export type GridSkip =
  | { readonly kind: 'nodes'; readonly nodes: number }
  | { readonly kind: 'legs'; readonly legs: number }
  | { readonly kind: 'size'; readonly width: number; readonly height: number }
  | { readonly kind: 'overlap'; readonly what: 'box' | 'label'; readonly on: 'outside' | 'text' | 'line'; readonly x: number; readonly y: number }

/** The grid, or why there is none. */
export type GridResult = { readonly kind: 'grid'; readonly grid: FlowGrid } | { readonly kind: 'skip'; readonly reason: GridSkip }

const skipFor = (reason: GridSkip): GridResult => ({ kind: 'skip', reason })

// a line cell's connections, in screen directions
const N = 1
const E = 2
const S = 4
const W = 8

type Glyphs = Record<number, string>
const SOLID: Glyphs = {
  [N]: '│', [S]: '│', [N | S]: '│', [E]: '─', [W]: '─', [E | W]: '─',
  [S | E]: '┌', [S | W]: '┐', [N | E]: '└', [N | W]: '┘',
  [N | S | E]: '├', [N | S | W]: '┤', [E | W | S]: '┬', [E | W | N]: '┴', [N | E | S | W]: '┼',
}
const THICK: Glyphs = {
  [N]: '║', [S]: '║', [N | S]: '║', [E]: '═', [W]: '═', [E | W]: '═',
  [S | E]: '╔', [S | W]: '╗', [N | E]: '╚', [N | W]: '╝',
  [N | S | E]: '╠', [N | S | W]: '╣', [E | W | S]: '╦', [E | W | N]: '╩', [N | E | S | W]: '╬',
}
// dotted has straight glyphs only; its corners and junctions take the solid ones
const DOTTED: Glyphs = { ...SOLID, [N]: '┆', [S]: '┆', [N | S]: '┆', [E]: '┄', [W]: '┄', [E | W]: '┄' }

const STYLE_BIT: Record<EdgeStyle, number> = { solid: 1, open: 1, dotted: 2, thick: 4 }
const STYLE_GLYPHS: Record<number, Glyphs> = { 1: SOLID, 2: DOTTED, 4: THICK }

const CORNERS: Record<NodeShape, [string, string, string, string]> = {
  rect: ['┌', '┐', '└', '┘'],
  round: ['╭', '╮', '╰', '╯'],
  circle: ['╭', '╮', '╰', '╯'],
  diamond: ['╱', '╲', '╲', '╱'],
}

const HEAD: Record<Direction, string> = { LR: '►', RL: '◄', TD: '▼', TB: '▼', BT: '▲' }

/** One leg of a forward edge across one gap: from a box or a slot in layer g to a box or a slot in layer g + 1. */
type Leg = { edge: FlowEdge; src: string; sc: number; tc: number; toBox: boolean; label: string }

/** A gap's channel owners in order: by cross position, except that a source whose line stops at its channel goes before any source whose line ends on that row, so the two never share cells. */
const channelOrder = (owners: { key: string; sc: number; legs: Leg[] }[]): string[] => {
  const left = [...owners].sort((a, b) => a.sc - b.sc)
  const stops = (b: { sc: number; legs: Leg[] }): boolean => !b.legs.some(l => l.tc === b.sc)
  const mustPrecede = (b: (typeof left)[number], a: (typeof left)[number]): boolean => a !== b && stops(b) && a.legs.some(l => l.tc === b.sc)
  const out: string[] = []
  while (left.length > 0) {
    // the first owner with nothing left that must precede it; on a cycle, the first by position
    const i = Math.max(0, left.findIndex(a => !left.some(b => mustPrecede(b, a))))
    const [next] = left.splice(i, 1)
    if (next === undefined) break
    out.push(next.key)
  }
  return out
}

/**
 * The terminal picture (ADR 0003): rows of box-drawing cells, each exactly `width` wide. Boxes
 * `│ label │` three rows high (square, rounded or slanted corners by shape); layers left to
 * right (LR, RL mirrored) or top to bottom (TD, TB, BT mirrored); each forward edge a line
 * from a stub through its source's channel to a head `►` `◄` `▼` `▲` (none when open), `─`
 * solid, `┄` dotted, `═` thick, junctions and crossings composed; edge labels on the line;
 * an edge that spans layers runs through a slot under each layer between. Back edges are not
 * drawn but returned. Labels cut to 24 cells. Identical edges are drawn once. A skip, before
 * any cell is allocated, past `GRID_NODE_LIMIT` nodes (`nodes`), past `GRID_LEG_LIMIT` forward
 * legs (`legs`) or past `GRID_CELL_LIMIT` cells (`size`). A box or label that would land on a
 * line, on other text or outside the grid is the `overlap` skip: never a throw.
 */
export function flowchartGrid(chart: Flowchart, direction: Direction = chart.direction): GridResult {
  if (chart.nodes.length > GRID_NODE_LIMIT) return skipFor({ kind: 'nodes', nodes: chart.nodes.length })
  const { layers } = layoutFlowchart(chart)
  const flat = horizontal(direction)
  const mirror = direction === 'RL' || direction === 'BT'
  const nodes = new Map(chart.nodes.map(n => [n.id, n]))
  const text = (id: string): string => cutLabel(nodes.get(id)?.label ?? id)
  const len = (s: string): number => [...s].length
  const along = (id: string): number => (flat ? len(text(id)) + 4 : 3)
  const across = (id: string): number => (flat ? 3 : len(text(id)) + 4)

  const layerOf = new Map<string, number>()
  layers.forEach((ids, l) => ids.forEach(id => layerOf.set(id, l)))
  const backEdges: FlowEdge[] = []
  const forward: { edge: FlowEdge; index: number; lf: number; lt: number }[] = []
  // an identical edge twice is one line: a duplicate would double its legs and slots
  const seen = new Set<string>()
  const edges = chart.edges.filter(e => {
    const k = JSON.stringify([e.from, e.to, e.label, e.style])
    if (seen.has(k)) return false
    seen.add(k)
    return true
  })
  edges.forEach((edge, index) => {
    const lf = layerOf.get(edge.from) ?? 0
    const lt = layerOf.get(edge.to) ?? 0
    if (lt <= lf) backEdges.push(edge)
    else forward.push({ edge, index, lf, lt })
  })
  const legCount = forward.reduce((sum, f) => sum + (f.lt - f.lf), 0)
  if (legCount > GRID_LEG_LIMIT) return skipFor({ kind: 'legs', legs: legCount })

  // Cross axis: boxes stacked one cell apart, then a blank and a slot per edge passing through.
  const slots: string[][] = layers.map(() => [])
  for (const f of forward) for (let l = f.lf + 1; l < f.lt; l++) slots[l]?.push(`${l}:${f.index}`)
  const extent = layers.map((ids, l) => ids.reduce((sum, id) => sum + across(id), 0) + ids.length - 1 + 2 * (slots[l]?.length ?? 0))
  const crossTotal = Math.max(0, ...extent)
  const start = new Map<string, number>()
  const mid = new Map<string, number>()
  layers.forEach((ids, l) => {
    let c = Math.floor((crossTotal - (extent[l] ?? 0)) / 2)
    for (const id of ids) {
      start.set(id, c)
      mid.set(id, c + Math.floor((across(id) - 1) / 2))
      c += across(id) + 1
    }
    slots[l]?.forEach((key, k) => mid.set(key, c + 2 * k))
  })

  // Main axis: each gap holds a stub, its channels, the label run and the head cell.
  const thickness = layers.map(ids => Math.max(...ids.map(along)))
  const legs: Leg[][] = layers.slice(1).map(() => [])
  for (const f of forward)
    for (let g = f.lf; g < f.lt; g++) {
      const src = g === f.lf ? f.edge.from : `${g}:${f.index}`
      const toBox = g + 1 === f.lt
      const tgt = toBox ? f.edge.to : `${g + 1}:${f.index}`
      legs[g]?.push({ edge: f.edge, src, sc: mid.get(src) ?? 0, tc: mid.get(tgt) ?? 0, toBox, label: toBox ? f.edge.label : '' })
    }
  const gaps = legs.map(gapLegs => {
    const bySource = new Map<string, Leg[]>()
    for (const leg of gapLegs) bySource.set(leg.src, [...(bySource.get(leg.src) ?? []), leg])
    const owners = [...bySource].filter(([, ls]) => ls.some(l => l.tc !== l.sc)).map(([key, ls]) => ({ key, sc: ls[0]?.sc ?? 0, legs: ls }))
    const channels = channelOrder(owners)
    const labels = new Map<number, string>()
    for (const tc of [...new Set(gapLegs.map(l => l.tc))].sort((a, b) => a - b)) {
      const texts = [...new Set(gapLegs.filter(l => l.tc === tc && l.label !== '').map(l => l.label))]
      if (texts.length > 0) labels.set(tc, cutLabel(texts.join(' / ')))
    }
    const longest = Math.max(0, ...[...labels.values()].map(len))
    const run = labels.size === 0 ? 1 : flat ? longest + 4 : labels.size + 2
    return { legs: gapLegs, bySource, channels, labels, longest, run, size: 1 + channels.length + run + 1 }
  })
  const layerStart: number[] = []
  const gapStart: number[] = []
  let m = 0
  layers.forEach((_, l) => {
    layerStart.push(m)
    m += thickness[l] ?? 0
    gapStart.push(m)
    m += gaps[l]?.size ?? 0
  })
  const mainTotal = m
  const crossSize = flat ? crossTotal : Math.max(crossTotal, ...gaps.map(g => g.longest))
  const width = flat ? mainTotal : crossSize
  const height = flat ? crossSize : mainTotal
  if (width * height > GRID_CELL_LIMIT) return skipFor({ kind: 'size', width, height })

  // Cells: line connections and styles, heads, and fixed text (boxes, labels) drawn over all.
  // a box or a label that would land where it must not; the first one skips the grid
  const overlaps: GridSkip[] = []
  const mask = Array.from({ length: height }, () => new Array<number>(width).fill(0))
  const style = Array.from({ length: height }, () => new Array<number>(width).fill(0))
  const head = Array.from({ length: height }, () => new Array<string | null>(width).fill(null))
  const fixed = Array.from({ length: height }, () => new Array<string | null>(width).fill(null))
  const at = (mm: number, c: number): [number, number] => {
    const mainPos = mirror ? mainTotal - 1 - mm : mm
    return flat ? [mainPos, c] : [c, mainPos]
  }
  const toward = (dm: number, dc: number): number => {
    if (dm !== 0) return flat ? (dm > 0) !== mirror ? E : W : (dm > 0) !== mirror ? S : N
    return flat ? (dc > 0 ? S : N) : dc > 0 ? E : W
  }
  const mark = (mm: number, c: number, bits: number, s: EdgeStyle): void => {
    const [x, y] = at(mm, c)
    const row = mask[y]
    const st = style[y]
    if (!row || !st || x < 0 || x >= width) return
    row[x] = (row[x] ?? 0) | bits
    st[x] = (st[x] ?? 0) | STYLE_BIT[s]
  }
  /** A straight run along one axis from (m1, c1) to (m2, c2), each cell linked to the next. */
  const line = (m1: number, c1: number, m2: number, c2: number, s: EdgeStyle): void => {
    const dm = Math.sign(m2 - m1)
    const dc = Math.sign(c2 - c1)
    for (let mm = m1, c = c1; mm !== m2 || c !== c2; mm += dm, c += dc) {
      mark(mm, c, toward(dm, dc), s)
      mark(mm + dm, c + dc, toward(-dm, -dc), s)
    }
  }

  gaps.forEach((gap, g) => {
    const gs = gapStart[g] ?? 0
    const headAt = gs + gap.size - 1
    const zone = gs + 1 + gap.channels.length
    for (const [src, srcLegs] of gap.bySource) {
      const sc = srcLegs[0]?.sc ?? 0
      // from the box's wall (or the slot's start) across the layer's spare room to the stub
      const from = nodes.has(src) ? (layerStart[g] ?? 0) + along(src) : (layerStart[g] ?? 0)
      for (const leg of srcLegs) {
        const s = leg.edge.style
        if (from < gs) line(from, sc, gs, sc, s)
        const ch = gs + 1 + gap.channels.indexOf(src)
        if (leg.tc === sc) line(gs, sc, headAt, sc, s)
        else {
          line(gs, sc, ch, sc, s)
          line(ch, sc, ch, leg.tc, s)
          line(ch, leg.tc, headAt, leg.tc, s)
        }
        if (!leg.toBox) line(headAt, leg.tc, (layerStart[g + 1] ?? 0) + (thickness[g + 1] ?? 0) - 1, leg.tc, s)
        else if (s !== 'open') {
          const [x, y] = at(headAt, leg.tc)
          const row = head[y]
          if (row) row[x] = HEAD[direction]
        }
      }
    }
    // labels: centred on the run in LR / RL; in TD / BT each on its own row of the run, centred on its line
    ;[...gap.labels].forEach(([tc, label], k) => {
      const n = len(label)
      if (flat) {
        const xs = [at(zone, tc)[0], at(zone + gap.run - 1, tc)[0]]
        put(Math.min(...xs) + Math.floor((gap.run - n) / 2), tc, label, 'label')
      } else {
        const y = at(zone + 1 + k, 0)[1]
        put(Math.max(0, Math.min(width - n, tc - Math.floor(n / 2))), y, label, 'label')
      }
    })
  })

  /** Fixed text at screen (x, y): a box never lands on a line, and nothing lands on fixed text; the first that would is the overlap. */
  function put(x: number, y: number, chars: string, what: 'box' | 'label'): void {
    ;[...chars].forEach((ch, i) => {
      const fx = fixed[y]
      const cx = x + i
      if (overlaps.length > 0) return
      if (!fx || cx < 0 || cx >= width) overlaps.push({ kind: 'overlap', what, on: 'outside', x: cx, y })
      else if (fx[cx] !== null) overlaps.push({ kind: 'overlap', what, on: 'text', x: cx, y })
      else if (what === 'box' && ((mask[y]?.[cx] ?? 0) !== 0 || head[y]?.[cx] != null)) overlaps.push({ kind: 'overlap', what, on: 'line', x: cx, y })
      else fx[cx] = ch
    })
  }

  layers.forEach((ids, l) => {
    for (const id of ids) {
      const node = nodes.get(id)
      const label = text(id)
      const [x1, y1] = at(layerStart[l] ?? 0, start.get(id) ?? 0)
      const [x2, y2] = at((layerStart[l] ?? 0) + along(id) - 1, (start.get(id) ?? 0) + across(id) - 1)
      const x = Math.min(x1, x2)
      const y = Math.min(y1, y2)
      const [tl, tr, bl, br] = CORNERS[node?.shape ?? 'rect']
      const bar = '─'.repeat(len(label) + 2)
      put(x, y, `${tl}${bar}${tr}`, 'box')
      put(x, y + 1, `│ ${label} │`, 'box')
      put(x, y + 2, `${bl}${bar}${br}`, 'box')
    }
  })

  const glyph = (x: number, y: number): string => {
    const bits = mask[y]?.[x] ?? 0
    if (bits === 0) return ' '
    const glyphs = STYLE_GLYPHS[style[y]?.[x] ?? 1] ?? SOLID
    return glyphs[bits] ?? SOLID[bits] ?? ' '
  }
  const overlap = overlaps[0]
  if (overlap !== undefined) return skipFor(overlap)
  const rows = Array.from({ length: height }, (_, y) =>
    Array.from({ length: width }, (_, x) => fixed[y]?.[x] ?? head[y]?.[x] ?? glyph(x, y)).join(''),
  )
  return { kind: 'grid', grid: { rows, backEdges, width } }
}
