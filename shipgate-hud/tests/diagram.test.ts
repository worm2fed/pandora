import { describe, expect, test } from 'claude-code/testing'

import { GRID_CELL_LIMIT, GRID_LEG_LIMIT, GRID_NODE_LIMIT, cut, flowchartGrid, flowchartSvg, flowchartText, layoutFlowchart, parseFlowchart, splitFences } from '../hooks/diagram'
import type { FlowGrid, Flowchart } from '../hooks/diagram'

const count = (text: string, needle: string): number => text.split(needle).length - 1

const CHART = [
  'flowchart LR',
  '  %% the request path',
  '  api[API gateway] -->|enqueue| queue((queue))',
  '  queue -- drain --> worker(worker)',
  '  worker -.-> store("store")',
  '  subgraph checks',
  '    worker --> ok{ok?}',
  '  end',
  '  ok --> api & cache',
  '  cache --> store --> api',
  '  classDef hot fill:#f00',
  '  style api fill:#fff',
].join('\n')

describe('diagram', () => {
  test('splitFences: mermaid and svg fences split out, other fences stay in the markdown', async () => {
    const md = [
      'Prose before.',
      '',
      '```mermaid',
      'flowchart LR',
      '  a --> b',
      '```',
      'Between.',
      '```ts',
      'const x = 1',
      '```',
      '```svg',
      '<svg></svg>',
      '```',
      'After.',
    ].join('\n')
    expect(splitFences(md)).toEqual([
      { kind: 'markdown', text: 'Prose before.\n' },
      { kind: 'fence', lang: 'mermaid', source: 'flowchart LR\n  a --> b' },
      { kind: 'markdown', text: 'Between.\n```ts\nconst x = 1\n```' },
      { kind: 'fence', lang: 'svg', source: '<svg></svg>' },
      { kind: 'markdown', text: 'After.' },
    ])
  })

  test('splitFences: a mermaid fence inside another fence stays markdown', async () => {
    const md = ['````md', '```mermaid', 'graph TD', '```', '````'].join('\n')
    expect(splitFences(md)).toEqual([{ kind: 'markdown', text: md }])
  })

  test('parseFlowchart: shapes, labels, styles, fan-out, chains, subgraph and comments', async () => {
    const chart = parseFlowchart(CHART)
    expect(chart?.direction).toBe('LR')
    expect(chart?.nodes).toEqual([
      { id: 'api', label: 'API gateway', shape: 'rect' },
      { id: 'queue', label: 'queue', shape: 'circle' },
      { id: 'worker', label: 'worker', shape: 'round' },
      { id: 'store', label: 'store', shape: 'round' },
      { id: 'ok', label: 'ok?', shape: 'diamond' },
      { id: 'cache', label: 'cache', shape: 'rect' },
    ])
    expect(chart?.edges).toEqual([
      { from: 'api', to: 'queue', label: 'enqueue', style: 'solid' },
      { from: 'queue', to: 'worker', label: 'drain', style: 'solid' },
      { from: 'worker', to: 'store', label: '', style: 'dotted' },
      { from: 'worker', to: 'ok', label: '', style: 'solid' },
      { from: 'ok', to: 'api', label: '', style: 'solid' },
      { from: 'ok', to: 'cache', label: '', style: 'solid' },
      { from: 'cache', to: 'store', label: '', style: 'solid' },
      { from: 'store', to: 'api', label: '', style: 'solid' },
    ])
  })

  test('parseFlowchart: thick, open, dotted and thick labels, quoted labels, <br/>, fan-in', async () => {
    const chart = parseFlowchart(
      ['graph TD', 'a["one<br/>two"] ==> b', 'b --- c', 'a -. maybe .-> c', 'a == hard ==> c', 'a & b --> d;'].join('\n'),
    )
    expect(chart?.direction).toBe('TD')
    expect(chart?.nodes[0]).toEqual({ id: 'a', label: 'one two', shape: 'rect' })
    expect(chart?.edges).toEqual([
      { from: 'a', to: 'b', label: '', style: 'thick' },
      { from: 'b', to: 'c', label: '', style: 'open' },
      { from: 'a', to: 'c', label: 'maybe', style: 'dotted' },
      { from: 'a', to: 'c', label: 'hard', style: 'thick' },
      { from: 'a', to: 'd', label: '', style: 'solid' },
      { from: 'b', to: 'd', label: '', style: 'solid' },
    ])
  })

  test('parseFlowchart: a missing direction defaults to TD; TB is kept', async () => {
    expect(parseFlowchart('flowchart\n a --> b')?.direction).toBe('TD')
    expect(parseFlowchart('flowchart TB\n a --> b')?.direction).toBe('TB')
  })

  test('parseFlowchart: other diagram kinds and empty sources are null', async () => {
    expect(parseFlowchart('sequenceDiagram\n  a->>b: hi')).toBeNull()
    expect(parseFlowchart('classDiagram\n  A <|-- B')).toBeNull()
    expect(parseFlowchart('')).toBeNull()
    expect(parseFlowchart('flowchart LR\n  %% nothing here')).toBeNull()
  })

  test('layoutFlowchart: layers by longest path from the sources', async () => {
    const chart = parseFlowchart('flowchart TD\n A --> B\n A --> C\n B --> D\n C --> D')
    expect(chart).not.toBeNull()
    if (!chart) return
    expect(layoutFlowchart(chart).layers).toEqual([['A'], ['B', 'C'], ['D']])
  })

  test('layoutFlowchart: a cycle terminates and layers both nodes', async () => {
    const chart = parseFlowchart('flowchart LR\n A --> B --> A')
    if (!chart) throw new Error('no chart')
    expect(layoutFlowchart(chart).layers).toEqual([['A'], ['B']])
  })

  test('layoutFlowchart: LR boxes advance in x, TD boxes in y; a long label widens its box', async () => {
    const lr = parseFlowchart('flowchart LR\n a --> b[a much longer label than the default box]')
    const td = parseFlowchart('flowchart TD\n a --> b')
    if (!lr || !td) throw new Error('no chart')
    const l = layoutFlowchart(lr)
    const t = layoutFlowchart(td)
    expect((l.boxes.b?.x ?? 0) > (l.boxes.a?.x ?? 0)).toBe(true)
    expect(l.boxes.a?.w).toBe(120)
    expect(l.boxes.a?.h).toBe(36)
    expect((l.boxes.b?.w ?? 0) > 120).toBe(true)
    expect((t.boxes.b?.y ?? 0) > (t.boxes.a?.y ?? 0)).toBe(true)
    expect(t.boxes.b?.x).toBe(t.boxes.a?.x)
  })

  test('flowchartSvg: one rect per node, one line per edge, an arrowhead, escaped labels', async () => {
    const chart = parseFlowchart('flowchart LR\n api["a <b> & c"] -->|x < y| queue[say "hi"]\n queue --- store\n store -.-> api')
    if (!chart) throw new Error('no chart')
    const svg = flowchartSvg(chart)
    expect(svg.startsWith('<svg')).toBe(true)
    expect(svg.endsWith('</svg>')).toBe(true)
    expect(svg).toContain('<marker')
    expect(count(svg, '<rect')).toBe(3)
    expect(count(svg, '<line')).toBe(3)
    expect(svg).toContain('a &lt;b&gt; &amp;')
    expect(svg).toContain('x &lt; y')
    expect(svg).toContain('say &quot;hi&quot;')
    expect(count(svg, 'marker-end')).toBe(2)
    expect(svg).toContain('stroke-dasharray')
    expect(svg).toContain('viewBox="0 0 ')
    expect(svg).not.toContain('var(')
    expect(svg).not.toContain('\n')
  })

  test('flowchartText: one line per layer, an edge line after each layer', async () => {
    const chart = parseFlowchart('flowchart LR\n api --> queue -->|push| store')
    if (!chart) throw new Error('no chart')
    expect(flowchartText(chart).split('\n')).toEqual([
      '[api]',
      '[api] ──► [queue]',
      '[queue]',
      '[queue] ──push──► [store]',
      '[store]',
    ])
  })

  test('flowchartText: nodes in a layer joined by three spaces; long labels cut with an ellipsis', async () => {
    const chart = parseFlowchart('flowchart TD\n a --> b[abcdefghijklmnopqrstuvwxyz0123]\n a --> c')
    if (!chart) throw new Error('no chart')
    const lines = flowchartText(chart).split('\n')
    expect(lines[0]).toBe('[a]')
    expect(lines[3]).toBe('[abcdefghijklmnopqrstuvw…]   [c]')
  })

  test('flowchartText: dotted, thick and open arrows', async () => {
    const chart = parseFlowchart('flowchart LR\n a -.-> b\n a ==> c\n a --- d\n a -. why .-> e')
    if (!chart) throw new Error('no chart')
    expect(flowchartText(chart).split('\n').slice(1, 5)).toEqual([
      '[a] ┄┄► [b]',
      '[a] ══► [c]',
      '[a] ─── [d]',
      '[a] ┄┄why┄┄► [e]',
    ])
  })

  test('parseFlowchart: doubled shapes map to the nearest supported shape', async () => {
    const shapes = (source: string) => parseFlowchart(`flowchart LR\n  ${source}`)
    for (const [source, label, shape] of [
      ['A[[sub]] --> B', 'sub', 'rect'],
      ['A{{hex}} --> B', 'hex', 'diamond'],
      ['A[(db)] --> B', 'db', 'round'],
      ['A([x]) --> B', 'x', 'round'],
      ['A>flag] --> B', 'flag', 'rect'],
    ] as const) {
      const chart = shapes(source)
      expect(chart?.nodes).toEqual([
        { id: 'A', label, shape },
        { id: 'B', label: 'B', shape: 'rect' },
      ])
      expect(chart?.edges).toEqual([{ from: 'A', to: 'B', label: '', style: 'solid' }])
    }
  })

  test('parseFlowchart: a statement with unparsed text left over is null, not a dropped edge', async () => {
    expect(parseFlowchart('flowchart LR\n  A[array[0]] --> B')).toBeNull()
    expect(parseFlowchart('flowchart LR\n  A --> B extra')).toBeNull()
  })

  test('parseFlowchart: a statement whose start cannot be read is null, not a skipped line', async () => {
    expect(parseFlowchart('flowchart LR\n  Ä --> B\n  A --> C')).toBeNull()
  })

  test('parseFlowchart: ids that start with a keyword are statements, the keywords alone are skipped', async () => {
    const chart = parseFlowchart(['flowchart LR', '  end-user --> api', '  style-guide --> x', '  style api fill:#fff', '  subgraph s', '  end'].join('\n'))
    expect(chart?.nodes.map(n => n.id)).toEqual(['end-user', 'api', 'style-guide', 'x'])
    expect(chart?.edges.map(e => `${e.from}>${e.to}`)).toEqual(['end-user>api', 'style-guide>x'])
  })

  test('parseFlowchart: statements on the header line parse', async () => {
    const chart = parseFlowchart('graph TD; A-->B; B-->C')
    expect(chart?.direction).toBe('TD')
    expect(chart?.edges.map(e => `${e.from}>${e.to}`)).toEqual(['A>B', 'B>C'])
  })

  test('flowchartSvg: the arrowhead marker id is per chart and the references match it', async () => {
    const ids = ['flowchart LR\n  a --> b', 'flowchart LR\n  c --> d'].map(source => {
      const svg = flowchartSvg(parseFlowchart(source) ?? { direction: 'LR', nodes: [], edges: [] })
      const id = /<marker id="(arrow-[0-9a-f]+)"/.exec(svg)?.[1]
      expect(id).toBeDefined()
      expect(svg).toContain(`marker-end="url(#${id})"`)
      return id
    })
    expect(ids[0]).not.toBe(ids[1])
  })

  test('cut: code points, spacing kept, an ellipsis when cut', async () => {
    expect(cut('[a]   [b]', 20)).toBe('[a]   [b]')
    expect(cut('[a]   [bcdef]', 8)).toBe('[a]   […')
    expect(cut('──►──►', 3)).toBe('──…')
  })
})

/** The chart parsed, or a thrown error: every grid test starts from a chart that parses. */
const chartOf = (source: string): Flowchart => {
  const chart = parseFlowchart(source)
  if (!chart) throw new Error(`no chart: ${source}`)
  return chart
}

/** The grid for a source, or a thrown error when the grid is skipped. */
const gridFor = (source: string, direction?: Flowchart['direction']): FlowGrid => {
  const grid = flowchartGrid(chartOf(source), direction)
  if ('skip' in grid) throw new Error(`no grid (${grid.skip}): ${source}`)
  return grid
}

/** The grid's rows for a source, or a thrown error when the grid is skipped. */
const gridOf = (source: string, direction?: Flowchart['direction']): string[] => gridFor(source, direction).rows

/** Expected rows as drawn, each padded to the widest one: the grid's rows all have its width. */
const padded = (rows: string[]): string[] => {
  const width = Math.max(...rows.map(r => [...r].length))
  return rows.map(r => r + ' '.repeat(width - [...r].length))
}

describe('flowchartGrid', () => {
  test('pinned: a fan-out bends through one channel column', async () => {
    const grid = gridFor('flowchart LR\n a --> b\n a --> c')
    expect(grid?.rows).toEqual(
      padded(['         ┌───┐', '      ┌─►│ b │', '┌───┐ │  └───┘', '│ a │─┤', '└───┘ │  ┌───┐', '      └─►│ c │', '         └───┘']),
    )
    expect(grid?.width).toBe(14)
    expect(grid?.backEdges).toEqual([])
  })

  test('pinned: a chain draws straight, the label on its line', async () => {
    expect(gridOf('flowchart LR\n api --> queue -->|push| store')).toEqual([
      '┌─────┐   ┌───────┐          ┌───────┐',
      '│ api │──►│ queue │───push──►│ store │',
      '└─────┘   └───────┘          └───────┘',
    ])
  })

  test('every row is exactly the grid width', async () => {
    const grid = gridFor('flowchart LR\n a --> b[a longer label]\n a --> c')
    for (const row of grid?.rows ?? []) expect([...row].length).toBe(grid?.width)
  })

  test('directions: LR left to right, RL mirrored, TD and TB top to bottom, BT mirrored', async () => {
    const lr = ['┌───┐   ┌───┐', '│ a │──►│ b │', '└───┘   └───┘']
    const rl = ['┌───┐   ┌───┐', '│ b │◄──│ a │', '└───┘   └───┘']
    const td = ['┌───┐', '│ a │', '└───┘', '  │  ', '  │  ', '  ▼  ', '┌───┐', '│ b │', '└───┘']
    const bt = ['┌───┐', '│ b │', '└───┘', '  ▲  ', '  │  ', '  │  ', '┌───┐', '│ a │', '└───┘']
    expect(gridOf('flowchart LR\n a --> b')).toEqual(lr)
    expect(gridOf('flowchart RL\n a --> b')).toEqual(rl)
    expect(gridOf('flowchart TD\n a --> b')).toEqual(td)
    expect(gridOf('flowchart TB\n a --> b')).toEqual(td)
    expect(gridOf('flowchart BT\n a --> b')).toEqual(bt)
    // the direction argument overrides the chart's
    expect(gridOf('flowchart LR\n a --> b', 'TD')).toEqual(td)
  })

  test('RL mirrors a bend: the channel sits left of the source, heads point left', async () => {
    expect(gridOf('flowchart RL\n a --> b\n a --> c')).toEqual(
      padded(['┌───┐', '│ b │◄─┐', '└───┘  │ ┌───┐', '       ├─│ a │', '┌───┐  │ └───┘', '│ c │◄─┘', '└───┘']),
    )
  })

  test('edge styles: solid, dotted, thick, open without a head', async () => {
    expect(gridOf('flowchart LR\n a -.-> b')[1]).toBe('│ a │┄┄►│ b │')
    expect(gridOf('flowchart LR\n a ==> b')[1]).toBe('│ a │══►│ b │')
    expect(gridOf('flowchart LR\n a --- b')[1]).toBe('│ a │───│ b │')
    expect(gridOf('flowchart TD\n a -.-> b').slice(3, 6)).toEqual(['  ┆  ', '  ┆  ', '  ▼  '])
    expect(gridOf('flowchart TD\n a ==> b').slice(3, 6)).toEqual(['  ║  ', '  ║  ', '  ▼  '])
    // a thick bend takes the double corners
    const thick = gridOf('flowchart LR\n a ==> b\n a ==> c')
    expect(thick.join('\n')).toContain('╔')
    expect(thick.join('\n')).toContain('╚')
    expect(thick.join('\n')).toContain('╣')
  })

  test('shapes: rect square corners, round and circle rounded, diamond slanted', async () => {
    expect(gridOf('flowchart LR\n a[x]')).toEqual(['┌───┐', '│ x │', '└───┘'])
    expect(gridOf('flowchart LR\n a(x)')).toEqual(['╭───╮', '│ x │', '╰───╯'])
    expect(gridOf('flowchart LR\n a((x))')).toEqual(['╭───╮', '│ x │', '╰───╯'])
    expect(gridOf('flowchart LR\n a{x}')).toEqual(['╱───╲', '│ x │', '╲───╱'])
  })

  test('a multi-layer edge passes through a slot under the middle layer, never through its box', async () => {
    const rows = gridOf('flowchart LR\n a --> b --> c\n a --> c')
    expect(rows).toEqual(
      padded([
        '         ┌───┐',
        '┌───┐ ┌─►│ b │─┐   ┌───┐',
        '│ a │─┤  └───┘ └┬─►│ c │',
        '└───┘ │         │  └───┘',
        '      └─────────┘',
      ]),
    )
  })

  test('a crossing draws ┼ where one line crosses another; a source whose line stops at its channel takes the earlier channel', async () => {
    // a's channel crosses b's stub; a's run to d crosses b's channel
    expect(gridOf('flowchart LR\n c\n d\n e\n a --> d\n a --> e\n b --> c')).toEqual(
      padded([
        '          ┌───┐',
        '       ┌─►│ c │',
        '┌───┐  │  └───┘',
        '│ a │─┐│',
        '└───┘ ││  ┌───┐',
        '      ├┼─►│ d │',
        '┌───┐ ││  └───┘',
        '│ b │─┼┘',
        '└───┘ │   ┌───┐',
        '      └──►│ e │',
        '          └───┘',
      ]),
    )
    // d's line stops at its channel on row 5, where a's line to c ends: d goes first, so the two never share a cell
    expect(gridOf('flowchart LR\n a --> b\n a --> c\n d --> b')).toEqual([
      '┌───┐     ┌───┐',
      '│ a │─┬┬─►│ b │',
      '└───┘ ││  └───┘',
      '      ││       ',
      '┌───┐ ││  ┌───┐',
      '│ d │─┘└─►│ c │',
      '└───┘     └───┘',
    ])
  })

  test('labels of edges that meet at one target share the run, joined', async () => {
    expect(gridOf('flowchart LR\n a -->|x| c\n b -->|y| c')[3]).toBe('      └┬──x / y──►│ c │')
  })

  test('TD: a straight chain of mixed widths stays straight; labels on their own rows', async () => {
    const rows = gridOf('flowchart TD\n a[api] -->|enqueue| b[queue]\n b --> c[worker]')
    expect(rows.slice(0, 8)).toEqual([' ┌─────┐  ', ' │ api │  ', ' └─────┘  ', '    │     ', '    │     ', ' enqueue  ', '    │     ', '    ▼     '])
    expect(rows.slice(11, 14)).toEqual(['    │     ', '    │     ', '    ▼     '])
  })

  test('a back edge is not routed: it is returned in backEdges', async () => {
    const grid = gridFor('flowchart LR\n a --> b --> a')
    expect(grid?.rows).toEqual(['┌───┐   ┌───┐', '│ a │──►│ b │', '└───┘   └───┘'])
    expect(grid?.backEdges).toEqual([{ from: 'b', to: 'a', label: '', style: 'solid' }])
  })

  test('an edge label sits on the line: centred in LR, on its own row in TD', async () => {
    expect(gridOf('flowchart LR\n a -->|go| b')[1]).toBe('│ a │───go──►│ b │')
    expect(gridOf('flowchart TD\n a -->|go| b').slice(3, 8)).toEqual(['  │  ', '  │  ', ' go  ', '  │  ', '  ▼  '])
  })

  test('labels are cut to 24 cells with an ellipsis', async () => {
    const rows = gridOf('flowchart LR\n a[abcdefghijklmnopqrstuvwxyz0123] -->|abcdefghijklmnopqrstuvwxyz0123| b')
    expect(rows[1]).toContain('│ abcdefghijklmnopqrstuvw… │')
    expect(rows[1]).toContain('──abcdefghijklmnopqrstuvw…──►')
  })

  test('more than 60 nodes is the nodes skip; 60 draws', async () => {
    const chain = (n: number) => `flowchart LR\n${Array.from({ length: n - 1 }, (_, i) => `  n${i} --> n${i + 1}`).join('\n')}`
    expect(GRID_NODE_LIMIT).toBe(60)
    expect(flowchartGrid(chartOf(chain(61)))).toEqual({ skip: 'nodes', nodes: 61 })
    expect(gridFor(chain(60)).rows.length).toBe(3)
  })

  test('more than 200 forward legs is the legs skip', async () => {
    // 25 nodes, an edge from each node to every later one: a layer each, 2600 legs
    const edges = Array.from({ length: 24 }, (_, i) => Array.from({ length: 24 - i }, (_, j) => `  n${i} --> n${i + j + 1}`)).flat()
    expect(GRID_LEG_LIMIT).toBe(200)
    expect(flowchartGrid(chartOf(`flowchart LR\n${edges.join('\n')}`))).toEqual({ skip: 'legs', legs: 2600 })
  })

  test('a grid over 40,000 cells is the size skip', async () => {
    // a TD fan of 59 labelled edges: 59 wide boxes side by side, a label row per edge
    const pad = (i: number) => String(i).padStart(4, '0')
    const fan = Array.from({ length: 59 }, (_, i) => `  a -->|label number ${pad(i)} xx| b${i}[node label ${pad(i)} xxxxxx]`)
    expect(GRID_CELL_LIMIT).toBe(40000)
    expect(flowchartGrid(chartOf(`flowchart TD\n${fan.join('\n')}`))).toEqual({ skip: 'size', width: 1592, height: 70 })
  })

  test('an identical edge twice draws one line and counts its legs once', async () => {
    expect(gridOf('flowchart LR\n a -->|go| b\n a -->|go| b')).toEqual(gridOf('flowchart LR\n a -->|go| b'))
    // 150 copies of a two-layer edge are 300 legs; once deduplicated they are 2
    const copies = Array.from({ length: 150 }, () => '  a --> c').join('\n')
    expect(gridOf(`flowchart LR\n a --> b --> c\n${copies}`)).toEqual(gridOf('flowchart LR\n a --> b --> c\n a --> c'))
  })

  test('control characters in labels are dropped from the grid and the text form', async () => {
    const chart = chartOf('flowchart LR\n a["x\u001b[2Jy"] -->|p\u0007q| b')
    expect(chart.nodes[0]?.label).toBe('xy')
    expect(chart.edges[0]?.label).toBe('pq')
    expect(gridFor('flowchart LR\n a["x\u001b[2Jy"] -->|p\u0007q| b').rows[1]).toBe('│ xy │───pq──►│ b │')
    expect(flowchartText(chart)).toContain('[xy] ──pq──► [b]')
    for (const line of flowchartText(chart).split('\n')) expect(line).not.toMatch(/[\u0000-\u001f\u007f-\u009f]/)
  })
})
