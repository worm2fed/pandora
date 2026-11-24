# shipgate configuration — pandora

pandora is a **plugin marketplace**: one git repo holding several independent plugins
(`shipgate/`, `shipgate-hud/`, `astrolabe/`), each its own deliverable with its own version.

Code signals leave out `shipgate/evals/` (`code_signals.exclude` in `.claude/shipgate.json`):
the eval fixture scripts churn with every calibration and would read as the hottest files in
the repo, but they are synthetic, not product code.

## Knowledge base

- Layout: PRDs, ADRs and worklogs live with the plugin they describe (`<plugin>/docs/prd/`,
  `<plugin>/docs/adr/`, a worklog beside its PRD as `<name>.worklog.md`), not in a shared
  top-level folder, because each plugin ships and versions separately. ADRs are numbered
  `NNNN-<title>.md` in sequence; a single-writer repo makes that safe.
- Page conventions: the plugin's own templates —
  `shipgate/skills/clarify/references/prd-template.md`,
  `shipgate/skills/design/references/adr-template.md`,
  `shipgate/skills/design/references/worklog-template.md`. Frontmatter as those define.
- Promotion targets:
  plugin behaviour and conventions → the relevant `<plugin>/README.md` or its skill files;
  decisions → that plugin's ADR home.

## Forge & tracker

- Issue tracker: GitHub issues on this same repo (`worm2fed/pandora`). Much of the work
  here is ad-hoc with no issue; that is fine — the branch and PR carry the context.
- Integration branch: `main`.
- Title/body rules: state which plugin a change targets, since one repo ships several.
  A version bump belongs in the same PR as the change that earns it — both
  `<plugin>/.claude-plugin/plugin.json` and the matching entry in
  `.claude-plugin/marketplace.json`, kept in lockstep.

## Close-out

- Tag the release: when the stream bumped a plugin's version, run `claude plugin tag
  --push` in that plugin's directory once the version-bump commit is on `main` (root
  `CLAUDE.md`).
- Tick the child: tick this issue in its tracking issue's task list, when it has one.

## Branching

- Pattern: `<type>/<slug>`, type ∈ feat | fix | chore. The issue id is optional here and
  usually absent — include it as `<type>/<issue-id>-<slug>` when an issue does exist.
- Examples: `feat/sqlite-journal`, `fix/hook-fast-path`, `chore/bump-astrolabe`.

## Security-sensitive areas

- **Anything under a plugin's `hooks/`.** Plugin hooks execute on the user's machine in
  every project they open, so a defect here has a blast radius far beyond this repo.
  Changes to hook scripts or `hooks/*.json` get the full `/security-review`, and the
  no-op-when-not-applicable path is treated as a correctness requirement, not an
  optimization.
- Anything that reads or writes outside the plugin's own directory.
- **Confidentiality of private-project evidence.** This repo is public; the rule and the
  placeholder forms live in the root `CLAUDE.md` ("Public repo"). Every worker and
  reviewer brief that touches docs, skills, tests or fixtures carries that section
  verbatim, and review treats a leak as a BLOCKER.

## Autonomy

- Extra escalations: publishing — a version bump released to the marketplace, or anything
  that changes what an already-installed plugin does on someone else's machine. Also any
  change to the hook contract itself (which events fire, what can block a session).
