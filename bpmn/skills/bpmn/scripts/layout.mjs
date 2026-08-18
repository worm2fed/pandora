#!/usr/bin/env node
/**
 * layout.mjs — generate BPMN DI (diagram coordinates) for a semantic-only .bpmn file.
 *
 * Usage: node layout.mjs <file.bpmn> [-o <out.bpmn>]   (default: in-place)
 *
 * Handles three shapes of input:
 *   1. single process, no lanes  → bpmn-auto-layout as-is
 *   2. single process with lanes → auto-layout, then re-band elements into
 *      horizontal lane rows and re-route sequence flows (auto-layout ignores lanes)
 *   3. collaboration (pools)     → lay out each participant's process
 *      independently, stack pools vertically, route message flows between them
 *
 * Any pre-existing DI is discarded — layout is idempotent from semantics.
 */

import { readFileSync, writeFileSync } from 'node:fs';
import { BpmnModdle } from 'bpmn-moddle';
import { layoutProcess } from 'bpmn-auto-layout';

const LANE_ROW_H = 130; // vertical space per stacked row inside a lane
const LANE_PAD_Y = 30; // padding above/below rows inside a lane
const LANE_COL_W = 170; // column pitch for rank-based x in laned processes
const LANE_HEADER = 30; // width of the rotated lane-name band
const LANE_CONTENT_PAD = 70; // room between the name band and column 0, so
// event labels (wider than the 36px circle) don't spill over the lane name
const POOL_HEADER = 30; // width of the rotated pool-name band
const POOL_PAD_X = 40; // content inset inside a pool (after headers)
const POOL_PAD_Y = 25;
const POOL_GAP = 50; // vertical gap between stacked pools
const ORIGIN_X = 40;
const ORIGIN_Y = 40;

// label rects placed so far in this run (used for label deconfliction)
const placedLabels = [];

// ---------------------------------------------------------------------------
// entry
// ---------------------------------------------------------------------------

const args = process.argv.slice(2);
const outFlag = args.indexOf('-o');
const outFile = outFlag !== -1 ? args[outFlag + 1] : null;
const inFile = args.filter((a, i) => outFlag === -1 || (i !== outFlag && i !== outFlag + 1))[0];

if (!inFile) {
  console.error('usage: node layout.mjs <file.bpmn> [-o <out.bpmn>]');
  process.exit(2);
}

const moddle = new BpmnModdle();
const inputXml = readFileSync(inFile, 'utf8');
const { rootElement: defs } = await moddle.fromXML(inputXml);

// idempotency: throw away any existing diagram
defs.diagrams = [];

const collaboration = (defs.rootElements || []).find(
  (el) => el.$type === 'bpmn:Collaboration',
);

let outXml;
if (collaboration) {
  outXml = await layoutCollaboration(defs, collaboration);
} else {
  const proc = (defs.rootElements || []).find((el) => el.$type === 'bpmn:Process');
  if (!proc) {
    console.error('error: no bpmn:Process found in file');
    process.exit(1);
  }
  outXml = hasLanes(proc)
    ? await layoutProcessWithLanes(defs, proc)
    : await layoutPlainProcess(defs);
}

writeFileSync(outFile || inFile, outXml);
console.log(`layout written: ${outFile || inFile}`);

// ---------------------------------------------------------------------------
// case 1 — plain single process: bpmn-auto-layout end to end
// ---------------------------------------------------------------------------

async function layoutPlainProcess(defs) {
  const { xml } = await moddle.toXML(defs, { format: true });
  return layoutProcess(xml);
}

// ---------------------------------------------------------------------------
// case 2 — single process with lanes
// ---------------------------------------------------------------------------

async function layoutProcessWithLanes(defs, proc) {
  const geo = localGeometry(proc);
  const laneBands = bandIntoLanes(proc, geo);

  const bbox = geometryBBox(geo);
  const laneX = ORIGIN_X + LANE_HEADER;
  const laneW = LANE_HEADER + LANE_CONTENT_PAD + bbox.maxX + POOL_PAD_X;

  const plane = [];
  for (const band of laneBands) {
    plane.push(
      makeShape(band.lane, {
        x: laneX,
        y: ORIGIN_Y + band.y,
        width: laneW,
        height: band.height,
      }, { isHorizontal: true }),
    );
  }
  // content starts after the lane's own name band plus label breathing room
  emitGeometry(plane, geo, defs, { dx: laneX + LANE_HEADER + LANE_CONTENT_PAD, dy: ORIGIN_Y });

  attachDiagram(defs, proc, plane);
  const { xml } = await moddle.toXML(defs, { format: true });
  return xml;
}

// ---------------------------------------------------------------------------
// case 3 — collaboration: per-pool layout, vertical stacking, message flows
// ---------------------------------------------------------------------------

async function layoutCollaboration(defs, collaboration) {
  const plane = [];
  const globalShapes = new Map(); // element id -> absolute bounds (for message flows)
  const participantBounds = new Map(); // participant id -> bounds

  let yCursor = ORIGIN_Y;
  const poolInfos = [];

  // first pass: lay out every pool's content, remember content sizes
  for (const participant of collaboration.participants || []) {
    const proc = participant.processRef;
    let geo = null;
    let laneBands = null;
    if (proc && (proc.flowElements || []).length) {
      if (hasLanes(proc)) {
        geo = localGeometry(proc);
        laneBands = bandIntoLanes(proc, geo);
      } else {
        geo = await autoLayoutGeometry(proc);
      }
    }
    poolInfos.push({ participant, proc, geo, laneBands });
  }

  const contentW = Math.max(
    200,
    ...poolInfos.map((p) => (p.geo ? geometryBBox(p.geo).maxX : 0)),
  );
  const anyLanes = poolInfos.some((p) => p.laneBands);
  const headerW = POOL_HEADER + (anyLanes ? LANE_HEADER + LANE_CONTENT_PAD : 0);
  const poolW = headerW + contentW + POOL_PAD_X;

  // second pass: emit DI with vertical offsets
  for (const { participant, geo, laneBands } of poolInfos) {
    let poolH;
    const contentX = ORIGIN_X + headerW;
    const contentY = yCursor + POOL_PAD_Y;

    if (laneBands) {
      poolH = laneBands.reduce((s, b) => s + b.height, 0) + 2 * POOL_PAD_Y;
      for (const band of laneBands) {
        plane.push(
          makeShape(band.lane, {
            x: ORIGIN_X + POOL_HEADER,
            y: contentY + band.y,
            width: poolW - POOL_HEADER,
            height: band.height,
          }, { isHorizontal: true }),
        );
      }
    } else if (geo) {
      poolH = geometryBBox(geo).maxY + 2 * POOL_PAD_Y;
    } else {
      poolH = 100; // black-box pool
    }

    const bounds = { x: ORIGIN_X, y: yCursor, width: poolW, height: poolH };
    plane.push(makeShape(participant, bounds, { isHorizontal: true }));
    participantBounds.set(participant.id, bounds);

    if (geo) {
      emitGeometry(plane, geo, defs, { dx: contentX, dy: contentY }, globalShapes);
    }
    yCursor += poolH + POOL_GAP;
  }

  // message flows between pools
  for (const mf of collaboration.messageFlows || []) {
    const s = globalShapes.get(mf.sourceRef?.id) || participantBounds.get(mf.sourceRef?.id);
    const t = globalShapes.get(mf.targetRef?.id) || participantBounds.get(mf.targetRef?.id);
    if (!s || !t) {
      console.warn(`warn: message flow ${mf.id} has unresolved endpoints — skipped`);
      continue;
    }
    plane.push(makeEdge(mf, routeMessageFlow(s, t, poolGapMid(s, t, participantBounds))));
  }

  attachDiagram(defs, collaboration, plane);
  const { xml } = await moddle.toXML(defs, { format: true });
  return xml;
}

// ---------------------------------------------------------------------------
// geometry sources
// ---------------------------------------------------------------------------

/**
 * Geometry for laned processes: only element SIZES matter (ranks assign x,
 * lane bands assign y, all edges are re-routed), so skip bpmn-auto-layout
 * entirely — its traversal also chokes on entry points that aren't start
 * events (e.g. link catches).
 */
function localGeometry(proc) {
  const geo = { shapes: new Map(), edges: new Map() };
  for (const el of proc.flowElements || []) {
    if (el.$type === 'bpmn:SequenceFlow') continue;
    const size = /Task|SubProcess|CallActivity/.test(el.$type)
      ? { width: 100, height: 80 }
      : /Gateway/.test(el.$type)
        ? { width: 50, height: 50 }
        : { width: 36, height: 36 }; // events
    geo.shapes.set(el.id, { x: 0, y: 0, ...size });
  }
  return geo;
}

async function autoLayoutGeometry(proc) {
  const standalone = moddle.create('bpmn:Definitions', {
    id: `Defs_${proc.id}`,
    targetNamespace: 'http://bpmn.io/schema/bpmn',
    rootElements: [proc],
  });
  const { xml: subXml } = await moddle.toXML(standalone, { format: true });
  const laidOut = await layoutProcess(subXml);
  const { rootElement: subDefs } = await new BpmnModdle().fromXML(laidOut);

  const geo = { shapes: new Map(), edges: new Map() };
  const planeElements = subDefs.diagrams?.[0]?.plane?.planeElement || [];
  for (const pe of planeElements) {
    const id = pe.bpmnElement?.id;
    if (!id) continue;
    if (pe.$type === 'bpmndi:BPMNShape') {
      const b = pe.bounds;
      geo.shapes.set(id, { x: b.x, y: b.y, width: b.width, height: b.height });
    } else if (pe.$type === 'bpmndi:BPMNEdge') {
      geo.edges.set(id, (pe.waypoint || []).map((p) => ({ x: p.x, y: p.y })));
    }
  }
  return geo;
}

// ---------------------------------------------------------------------------
// lane banding: keep auto-layout x, re-assign y per lane; re-route flows
// ---------------------------------------------------------------------------

function hasLanes(proc) {
  return (proc.laneSets || []).some((ls) => (ls.lanes || []).length > 0);
}

/**
 * Longest-path layering: rank every flow node by its depth in the graph with
 * back edges removed. Auto-layout's x-order degrades badly on graphs with
 * loops, so laned processes get their columns from ranks instead.
 */
function computeRanks(proc) {
  const flowElements = proc.flowElements || [];
  const nodes = flowElements.filter(
    (el) => el.$type !== 'bpmn:SequenceFlow' && el.$type !== 'bpmn:BoundaryEvent',
  );
  const nodeIds = new Set(nodes.map((n) => n.id));

  // boundary events rank with their host: remap edges sourced from them
  const hostOf = new Map();
  for (const el of flowElements) {
    if (el.$type === 'bpmn:BoundaryEvent' && el.attachedToRef) {
      hostOf.set(el.id, el.attachedToRef.id);
    }
  }
  const edges = flowElements
    .filter((el) => el.$type === 'bpmn:SequenceFlow' && el.sourceRef && el.targetRef)
    .map((f) => ({
      source: hostOf.get(f.sourceRef.id) || f.sourceRef.id,
      target: f.targetRef.id,
      viaBoundary: hostOf.has(f.sourceRef.id),
    }))
    .filter((e) => nodeIds.has(e.source) && nodeIds.has(e.target) && e.source !== e.target);

  // DFS back-edge detection (white/gray/black). Exploration order matters:
  // follow the mainline first — low-indegree targets before join hubs, and
  // boundary-event exception paths last — so loops (not the primary flow)
  // get classified as the back edges.
  const indegAll = new Map([...nodeIds].map((id) => [id, 0]));
  for (const e of edges) indegAll.set(e.target, indegAll.get(e.target) + 1);
  const out = new Map([...nodeIds].map((id) => [id, []]));
  for (const e of edges) out.get(e.source).push(e);
  for (const list of out.values()) {
    list.sort(
      (a, b) =>
        (a.viaBoundary ? 1 : 0) - (b.viaBoundary ? 1 : 0) ||
        indegAll.get(a.target) - indegAll.get(b.target),
    );
  }
  const color = new Map();
  const forward = [];
  const order = new Map(); // DFS discovery order — mainline nodes come first
  const dfs = (id) => {
    color.set(id, 'gray');
    order.set(id, order.size);
    for (const e of out.get(id)) {
      const c = color.get(e.target);
      if (c === 'gray') continue; // back edge — drop
      forward.push(e);
      if (!c) dfs(e.target);
    }
    color.set(id, 'black');
  };
  const hasIncoming = new Set(edges.map((e) => e.target));
  for (const n of nodes) if (!hasIncoming.has(n.id)) dfs(n.id);
  for (const n of nodes) if (!color.has(n.id)) dfs(n.id); // cycle-only components

  // longest path over the forward DAG
  const rank = new Map([...nodeIds].map((id) => [id, 0]));
  const indeg = new Map([...nodeIds].map((id) => [id, 0]));
  const fout = new Map([...nodeIds].map((id) => [id, []]));
  for (const e of forward) {
    indeg.set(e.target, indeg.get(e.target) + 1);
    fout.get(e.source).push(e.target);
  }
  const queue = [...nodeIds].filter((id) => indeg.get(id) === 0);
  while (queue.length) {
    const id = queue.shift();
    for (const t of fout.get(id)) {
      rank.set(t, Math.max(rank.get(t), rank.get(id) + 1));
      indeg.set(t, indeg.get(t) - 1);
      if (indeg.get(t) === 0) queue.push(t);
    }
  }
  return { rank, order };
}

function bandIntoLanes(proc, geo) {
  const lanes = proc.laneSets[0].lanes;
  const flowElements = proc.flowElements || [];
  const byId = new Map(flowElements.map((el) => [el.id, el]));

  // rank-based columns (auto-layout x is unreliable on loopy graphs)
  const { rank: ranks, order } = computeRanks(proc);
  for (const [id, r] of ranks) {
    const shape = geo.shapes.get(id);
    if (!shape) continue;
    // center each element within its column (tasks 100 wide, gateways 50, events 36)
    const x = r * LANE_COL_W + Math.round((100 - shape.width) / 2);
    geo.shapes.set(id, { ...shape, x });
  }

  const bands = [];
  let bandTop = 0;

  for (const lane of lanes) {
    const memberIds = (lane.flowNodeRef || [])
      .map((ref) => ref.id)
      .filter((id) => geo.shapes.has(id) && byId.get(id)?.$type !== 'bpmn:BoundaryEvent');

    // greedy row assignment: same row while x-ranges don't overlap.
    // Pack in DFS discovery order so the mainline claims row 0 and exception
    // paths stack below it — not by column position, which lets a side path
    // that happens to start early steal the top row.
    const items = memberIds
      .map((id) => ({ id, ...geo.shapes.get(id) }))
      .sort((a, b) => (order.get(a.id) ?? 1e9) - (order.get(b.id) ?? 1e9));
    const rows = [];
    for (const it of items) {
      let r = rows.findIndex((row) =>
        row.every((o) => o.x + o.width + 30 <= it.x || it.x + it.width + 30 <= o.x),
      );
      if (r === -1) {
        rows.push([]);
        r = rows.length - 1;
      }
      rows[r].push(it);
      it.row = r;
    }

    const height = Math.max(rows.length, 1) * LANE_ROW_H + 2 * LANE_PAD_Y;
    for (const it of items) {
      const cy = bandTop + LANE_PAD_Y + it.row * LANE_ROW_H + LANE_ROW_H / 2;
      const prev = geo.shapes.get(it.id);
      geo.shapes.set(it.id, { ...prev, y: Math.round(cy - prev.height / 2) });
    }
    bands.push({ lane, y: bandTop, height });
    bandTop += height;
  }

  // re-attach boundary events to their (possibly moved) hosts
  for (const el of flowElements) {
    if (el.$type !== 'bpmn:BoundaryEvent' || !el.attachedToRef) continue;
    const host = geo.shapes.get(el.attachedToRef.id);
    if (!host) continue;
    geo.shapes.set(el.id, {
      x: Math.round(host.x + host.width * 0.65 - 18),
      y: Math.round(host.y + host.height - 18),
      width: 36,
      height: 36,
    });
  }

  // re-route every sequence flow (old waypoints are invalid after re-banding)
  for (const el of flowElements) {
    if (el.$type !== 'bpmn:SequenceFlow') continue;
    const s = geo.shapes.get(el.sourceRef?.id);
    const t = geo.shapes.get(el.targetRef?.id);
    if (!s || !t) continue;
    const obstacles = [...geo.shapes.entries()]
      .filter(([id]) => id !== el.sourceRef.id && id !== el.targetRef.id)
      .map(([, b]) => b);
    const fromBoundary = byId.get(el.sourceRef.id)?.$type === 'bpmn:BoundaryEvent';
    geo.edges.set(el.id, routeSequenceFlow(s, t, obstacles, fromBoundary));
  }

  return bands;
}

/** Does a horizontal segment at `y` spanning [x1, x2] cut through any shape? */
function hitsShape(x1, x2, y, obstacles) {
  const [lo, hi] = x1 < x2 ? [x1, x2] : [x2, x1];
  return obstacles.some(
    (b) => lo < b.x + b.width && hi > b.x && y > b.y - 8 && y < b.y + b.height + 8,
  );
}

/** Does a vertical segment at `x` spanning [y1, y2] cut through any shape? */
function hitsShapeV(y1, y2, x, obstacles) {
  const [lo, hi] = y1 < y2 ? [y1, y2] : [y2, y1];
  return obstacles.some(
    (b) => lo < b.y + b.height && hi > b.y && x > b.x - 8 && x < b.x + b.width + 8,
  );
}

/** Nearest clear horizontal channel from `y`, scanning in `dir` (+1 down / -1 up). */
function clearChannel(x1, x2, y, obstacles, dir = 1) {
  let ch = y;
  for (let i = 0; i < 12 && hitsShape(x1, x2, ch, obstacles); i++) ch += 20 * dir;
  return ch;
}

/**
 * Route the way a person draws BPMN:
 * - same row, forward  → straight right-to-left
 * - branch to another row → exit bottom/top, drop to the target's row, enter LEFT
 * - loop back          → exit bottom (or top), arc through a clear channel,
 *                        re-enter the target's bottom (or top)
 * Verticals prefer shape centers; when occupied they slide into the column
 * gutter. Horizontals are collision-checked and pushed into clear channels.
 * `isBoundarySource` forces a bottom exit (boundary events sit on the host's
 * bottom edge — exiting upward would cross the host).
 */
function routeSequenceFlow(s, t, obstacles = [], isBoundarySource = false) {
  const sR = s.x + s.width;
  const tR = t.x + t.width;
  const sCx = s.x + s.width / 2;
  const tCx = t.x + t.width / 2;
  const sCy = s.y + s.height / 2;
  const tCy = t.y + t.height / 2;
  const sB = s.y + s.height;
  const tB = t.y + t.height;
  const sameRow = Math.abs(sCy - tCy) < 25;

  // exception path: drop from the boundary icon into a clear channel, run
  // toward the target, rise in the gutter beside it, enter from the side
  if (isBoundarySource) {
    const toRight = tCx >= sCx;
    const ch = clearChannel(Math.min(sCx, tCx) - 25, Math.max(sCx, tCx) + 25, sB + 30, obstacles);
    let gx = toRight ? t.x - 25 : tR + 25;
    for (let i = 0; hitsShapeV(ch, tCy, gx, obstacles) && i < 5; i++) {
      gx += toRight ? -10 : 10;
    }
    return [
      { x: sCx, y: sB },
      { x: sCx, y: ch },
      { x: gx, y: ch },
      { x: gx, y: tCy },
      { x: toRight ? t.x : tR, y: tCy },
    ];
  }

  // ---- forward ----
  if (t.x >= sR + 20) {
    if (sameRow && !isBoundarySource) {
      if (!hitsShape(sR, t.x, sCy, obstacles)) {
        return [{ x: sR, y: sCy }, { x: t.x, y: tCy }];
      }
      // occupied row: arc through the nearest clear channel below
      const ch = clearChannel(sR + 25, t.x - 25, Math.max(sB, tB) + 42, obstacles);
      return [
        { x: sCx, y: sB },
        { x: sCx, y: ch },
        { x: tCx, y: ch },
        { x: tCx, y: tB },
      ];
    }

    // branch to another row: exit bottom (target below) or top (target above),
    // drop to the target's row, enter the target's LEFT side
    const down = tCy > sCy || isBoundarySource;
    const exitY = down ? sB : s.y;
    let vx = sCx;
    if (hitsShapeV(exitY, tCy, vx, obstacles)) vx = sR + 25; // slide into the gutter
    const start =
      vx === sR + 25
        ? [{ x: sR, y: sCy }, { x: vx, y: sCy }]
        : [{ x: vx, y: exitY }];
    if (!hitsShape(vx, t.x, tCy, obstacles)) {
      return [...start, { x: vx, y: tCy }, { x: t.x, y: tCy }];
    }
    // target's row is occupied on approach: channel past it, enter top/bottom
    const ch = clearChannel(vx, tCx, down ? Math.max(sB, tB) + 42 : Math.min(s.y, t.y) - 42, obstacles, down ? 1 : -1);
    let enx = tCx;
    if (hitsShapeV(ch, tCy, enx, obstacles)) enx = t.x - 25;
    if (enx === t.x - 25) {
      return [...start, { x: vx, y: ch }, { x: enx, y: ch }, { x: enx, y: tCy }, { x: t.x, y: tCy }];
    }
    return [...start, { x: vx, y: ch }, { x: enx, y: ch }, { x: enx, y: ch > tCy ? tB : t.y }];
  }

  // ---- same column: connect vertically ----
  if (s.x < tR + 20 && t.x < sR + 20) {
    const down = tCy > sCy;
    const sy = down ? sB : s.y;
    const ty = down ? t.y : tB;
    if (Math.abs(sCx - tCx) < 2) {
      return [{ x: sCx, y: sy }, { x: tCx, y: ty }];
    }
    const midY = Math.round((sy + ty) / 2);
    return [
      { x: sCx, y: sy },
      { x: sCx, y: midY },
      { x: tCx, y: midY },
      { x: tCx, y: ty },
    ];
  }

  // ---- back edge (loop): arc under (or over, if the target sits higher) ----
  const goUp = tB < s.y - 10 && !isBoundarySource; // target clearly above → arc over the top
  const dir = goUp ? -1 : 1;
  const exitY = goUp ? s.y : sB;
  // channel above → descend onto the target's TOP; channel below → rise into its BOTTOM
  const entryY = goUp ? t.y : tB;
  const baseCh = goUp ? Math.min(s.y, t.y) - 42 : Math.max(sB, tB) + 42;
  const ch = clearChannel(Math.min(tCx, sCx) - 25, Math.max(tCx, sCx) + 25, baseCh, obstacles, dir);
  let ex = sCx;
  if (hitsShapeV(exitY, ch, ex, obstacles)) ex = s.x - 25;
  let enx = tCx;
  if (hitsShapeV(ch, entryY, enx, obstacles)) enx = tR + 25;
  const first = ex === s.x - 25 ? [{ x: s.x, y: sCy }, { x: ex, y: sCy }] : [{ x: ex, y: exitY }];
  if (enx === tR + 25) {
    return [...first, { x: ex, y: ch }, { x: enx, y: ch }, { x: enx, y: tCy }, { x: tR, y: tCy }];
  }
  return [...first, { x: ex, y: ch }, { x: enx, y: ch }, { x: enx, y: entryY }];
}

/** Message flows run vertically between pools; the bend sits mid-gap between pools. */
function routeMessageFlow(s, t, gapMid) {
  const sCx = s.x + s.width / 2;
  const tCx = t.x + t.width / 2;
  const goingDown = s.y + s.height / 2 < t.y + t.height / 2;
  const sy = goingDown ? s.y + s.height : s.y;
  const ty = goingDown ? t.y : t.y + t.height;
  if (Math.abs(sCx - tCx) < 2) {
    return [{ x: sCx, y: sy }, { x: tCx, y: ty }];
  }
  const midY = gapMid ?? Math.round((sy + ty) / 2);
  return [
    { x: sCx, y: sy },
    { x: sCx, y: midY },
    { x: tCx, y: midY },
    { x: tCx, y: ty },
  ];
}

/** Vertical midpoint of the empty gap between the two pools the endpoints live in. */
function poolGapMid(s, t, participantBounds) {
  const pools = [...participantBounds.values()];
  const findPool = (b) =>
    pools.find(
      (p) =>
        b.y + b.height / 2 >= p.y &&
        b.y + b.height / 2 <= p.y + p.height &&
        b.x + b.width / 2 >= p.x &&
        b.x + b.width / 2 <= p.x + p.width,
    );
  const sPool = findPool(s);
  const tPool = findPool(t);
  if (!sPool || !tPool || sPool === tPool) return null;
  const upper = sPool.y < tPool.y ? sPool : tPool;
  const lower = sPool.y < tPool.y ? tPool : sPool;
  return Math.round((upper.y + upper.height + lower.y) / 2);
}

// ---------------------------------------------------------------------------
// DI emission helpers
// ---------------------------------------------------------------------------

function geometryBBox(geo) {
  let maxX = 0;
  let maxY = 0;
  for (const b of geo.shapes.values()) {
    maxX = Math.max(maxX, b.x + b.width);
    maxY = Math.max(maxY, b.y + b.height);
  }
  for (const pts of geo.edges.values()) {
    for (const p of pts) {
      maxX = Math.max(maxX, p.x);
      maxY = Math.max(maxY, p.y);
    }
  }
  return { maxX, maxY };
}

/** Push shapes+edges from a geometry into the plane, offset by (dx, dy). */
function emitGeometry(plane, geo, defs, { dx, dy }, globalShapes) {
  const byId = indexElements(defs);
  for (const [id, b] of geo.shapes) {
    const el = byId.get(id);
    if (!el) continue;
    const abs = { x: b.x + dx, y: b.y + dy, width: b.width, height: b.height };
    const extra = {};
    if (el.$type === 'bpmn:ExclusiveGateway') extra.isMarkerVisible = true;
    plane.push(makeShape(el, abs, extra));
    globalShapes?.set(id, abs);
  }
  for (const [id, pts] of geo.edges) {
    const el = byId.get(id);
    if (!el) continue;
    plane.push(makeEdge(el, pts.map((p) => ({ x: p.x + dx, y: p.y + dy }))));
  }
}

function indexElements(defs) {
  const map = new Map();
  const walk = (el) => {
    if (!el || typeof el !== 'object') return;
    if (el.id) map.set(el.id, el);
    for (const key of ['rootElements', 'flowElements', 'participants', 'messageFlows', 'laneSets', 'lanes', 'artifacts']) {
      const children = el[key];
      if (Array.isArray(children)) children.forEach(walk);
    }
  };
  walk(defs);
  return map;
}

function makeShape(el, bounds, extra = {}) {
  const shape = moddle.create('bpmndi:BPMNShape', {
    id: `${el.id}_di`,
    bpmnElement: el,
    bounds: moddle.create('dc:Bounds', {
      x: Math.round(bounds.x),
      y: Math.round(bounds.y),
      width: Math.round(bounds.width),
      height: Math.round(bounds.height),
    }),
    ...extra,
  });
  // register the shape itself as a keep-out zone so edge labels dodge it
  if (!/Lane|Participant/.test(el.$type)) {
    placedLabels.push({ ...bounds });
  }
  // gateways label ABOVE the diamond (default below collides with branch
  // exits); boundary events label BESIDE the icon (default below crosses the
  // lane border). Registered so edge labels dodge them.
  if (el.name && /Gateway/.test(el.$type)) {
    const width = Math.min(el.name.length * 6 + 6, 110);
    const rect = {
      x: Math.max(2, Math.round(bounds.x + bounds.width / 2 - width / 2)),
      y: Math.round(bounds.y - 22),
      width,
      height: 14,
    };
    placedLabels.push(rect);
    shape.label = moddle.create('bpmndi:BPMNLabel', { bounds: moddle.create('dc:Bounds', rect) });
  } else if (el.name && el.$type === 'bpmn:BoundaryEvent') {
    // left of the icon at its height — the outgoing edge drops from the icon's
    // bottom-center and rises far right, so the left side stays clear
    const width = Math.min(el.name.length * 6 + 6, 130);
    const height = el.name.length * 6 + 6 > 130 ? 28 : 14;
    const rect = {
      x: Math.round(bounds.x - width - 8),
      y: Math.round(bounds.y + bounds.height / 2 - height / 2),
      width,
      height,
    };
    placedLabels.push(rect);
    shape.label = moddle.create('bpmndi:BPMNLabel', { bounds: moddle.create('dc:Bounds', rect) });
  }
  return shape;
}

function makeEdge(el, waypoints) {
  const edge = moddle.create('bpmndi:BPMNEdge', {
    id: `${el.id}_di`,
    bpmnElement: el,
    waypoint: waypoints.map((p) =>
      moddle.create('dc:Point', { x: Math.round(p.x), y: Math.round(p.y) }),
    ),
  });
  // anchor labels near the edge's exit point — default midpoint placement
  // collides when several labeled edges share a corridor
  if (el.name) {
    const [p, q = p] = waypoints;
    const horizontal = Math.abs(q.y - p.y) < 2;
    const width = Math.min(el.name.length * 6 + 6, 110);
    const x = Math.round(horizontal ? Math.min(p.x, q.x) + 10 : p.x + 8);
    // candidate rows: near the exit point, off the line — above/below for
    // horizontal exits, beside the segment (source end) for vertical exits
    const goingDown = q.y > p.y;
    const candidates = horizontal
      ? Array.from({ length: 10 }, (_, i) => (i % 2 ? p.y + 10 + 18 * (i >> 1) : p.y - 24 - 18 * (i >> 1)))
      : Array.from({ length: 8 }, (_, i) => (goingDown ? p.y + 8 + 18 * i : p.y - 22 - 18 * i));
    const collides = (y) =>
      placedLabels.some(
        (o) =>
          x < o.x + o.width + 4 &&
          x + width + 4 > o.x &&
          y < o.y + o.height + 4 &&
          y + 14 + 4 > o.y,
      );
    const y = Math.round(candidates.find((c) => !collides(c)) ?? candidates.at(-1));
    const rect = { x, y, width, height: 14 };
    placedLabels.push(rect);
    edge.label = moddle.create('bpmndi:BPMNLabel', {
      bounds: moddle.create('dc:Bounds', rect),
    });
  }
  return edge;
}

function attachDiagram(defs, planeRoot, planeElements) {
  const plane = moddle.create('bpmndi:BPMNPlane', {
    id: `BPMNPlane_${planeRoot.id}`,
    bpmnElement: planeRoot,
    planeElement: planeElements,
  });
  const diagram = moddle.create('bpmndi:BPMNDiagram', {
    id: `BPMNDiagram_${planeRoot.id}`,
    plane,
  });
  defs.diagrams = [diagram];
}
