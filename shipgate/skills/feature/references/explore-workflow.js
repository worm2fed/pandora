export const meta = {
  name: 'shipgate-explore',
  description:
    'Explore a codebase through one or more lenses and return grounded findings plus the essential files',
  phases: [{ title: 'Explore', detail: 'one code-explorer per lens' }],
}

const EXPLORE = {
  type: 'object',
  properties: {
    findings: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          topic: { type: 'string' },
          detail: { type: 'string' },
          refs: { type: 'array', items: { type: 'string' } },
        },
        required: ['topic', 'detail', 'refs'],
        additionalProperties: false,
      },
    },
    essential_files: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          path: { type: 'string' },
          why: { type: 'string' },
        },
        required: ['path', 'why'],
        additionalProperties: false,
      },
    },
  },
  required: ['findings', 'essential_files'],
  additionalProperties: false,
}

const MAX_ESSENTIAL_FILES = 25
const MAX_FINDINGS_PER_LENS = 20
const PATH_SEGMENTS = 3

const lenses = (args && args.lenses) || []
const model = args && args.model
if (!model) {
  throw new Error('explore-workflow: args.model is required — Workflow agents otherwise inherit the session model')
}
if (!lenses.length) {
  throw new Error('explore-workflow: args.lenses must carry at least one {name, prompt} lens')
}
lenses.forEach((lens, index) => {
  const named = lens && typeof lens.name === 'string' && lens.name.trim() !== ''
  const prompted = lens && typeof lens.prompt === 'string' && lens.prompt.trim() !== ''
  if (!named || !prompted) {
    throw new Error(`explore-workflow: args.lenses[${index}] needs a non-empty name and a non-empty prompt`)
  }
})

const brief = typeof args.brief === 'string' ? args.brief.trim() : ''
if (!brief) {
  throw new Error('explore-workflow: args.brief is required — it is the only context the explorers get')
}

function clip(text, max) {
  const value = text === null || text === undefined ? '' : String(text)
  return value.length > max ? `${value.slice(0, max)}…` : value
}

// Explorers cite one file as 'src/x', './src/x' and as an absolute path; the trailing segments
// are the part they agree on, so the merge key keeps only those.
function normalizePath(path) {
  const segments = String(path)
    .replace(/^\.\//, '')
    .split('/')
    .filter((segment) => segment !== '')
  return segments.slice(-PATH_SEGMENTS).join('/')
}

phase('Explore')
log(`exploring through ${lenses.length} lens(es): ${lenses.map((l) => l.name).join(', ')}`)

const reports = await parallel(
  lenses.map(
    (lens) => () =>
      agent([lens.prompt, '', brief].join('\n'), {
        agentType: 'shipgate:code-explorer',
        schema: EXPLORE,
        phase: 'Explore',
        label: `explore:${lens.name}`,
        model,
      }).then((report) =>
        report
          ? {
              lens: lens.name,
              findings: (report.findings || []).filter(Boolean),
              essential_files: (report.essential_files || []).filter(Boolean),
            }
          : null,
      ),
  ),
)

const live = reports.filter(Boolean)
if (!live.length) {
  log(`all ${lenses.length} lens explorer(s) died — this run explored nothing, fall back to the agents path`)
  return { lenses: [], essentialFiles: [], aborted: 'no lens explorer returned' }
}
if (live.length < lenses.length) {
  log(`${lenses.length - live.length} lens explorer(s) returned nothing — continuing on the rest`)
}

const byPath = new Map()
for (const report of live) {
  for (const file of report.essential_files) {
    const path = normalizePath(file.path)
    const entry = byPath.get(path) || { path, why: [] }
    const why = clip(file.why, 200)
    if (!entry.why.some((seen) => seen.lens === report.lens && seen.why === why)) {
      entry.why.push({ lens: report.lens, why })
    }
    byPath.set(path, entry)
  }
}
const flagged = Array.from(byPath.values())
const essentialFiles = flagged.slice(0, MAX_ESSENTIAL_FILES)
if (flagged.length > essentialFiles.length) {
  log(
    `${flagged.length} essential file(s) flagged — keeping the first ${MAX_ESSENTIAL_FILES} by first mention, ` +
      `dropping: ${flagged.slice(MAX_ESSENTIAL_FILES).map((f) => f.path).join(', ')}`,
  )
}

const perLens = live.map((report) => {
  const kept = report.findings.slice(0, MAX_FINDINGS_PER_LENS)
  if (report.findings.length > kept.length) {
    log(
      `lens ${report.lens} returned ${report.findings.length} finding(s) — keeping the first ` +
        `${MAX_FINDINGS_PER_LENS}, dropping ${report.findings.length - kept.length}`,
    )
  }
  return {
    lens: report.lens,
    findings: kept.map((finding) => ({
      topic: finding.topic,
      detail: clip(finding.detail, 600),
      refs: finding.refs || [],
    })),
  }
})

log(`${perLens.reduce((n, r) => n + r.findings.length, 0)} finding(s), ${essentialFiles.length} essential file(s)`)

return { lenses: perLens, essentialFiles }
